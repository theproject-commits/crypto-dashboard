import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from pycoingecko import CoinGeckoAPI

from .. import crud, schemas
from ..database import SessionLocal
from .composite_engine import compute_composite_v1
from .composite_v2_engine import compute_composite_v2
from .market_state_engine import compute_market_state
from .market_state_performance import compute_market_state_performance

logger = logging.getLogger("daily_update")
cg = CoinGeckoAPI()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_coin_ids(raw: str) -> list[str]:
    values = [coin.strip().lower() for coin in raw.split(",") if coin.strip()]
    return list(dict.fromkeys(values))


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(ys) < 3 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


class DailyUpdateScheduler:
    def __init__(self):
        self.enabled = _env_bool("DAILY_UPDATE_ENABLED", True)
        self.run_on_startup = _env_bool("DAILY_UPDATE_RUN_ON_STARTUP", True)
        self.lookback_days = _env_int("DAILY_UPDATE_LOOKBACK_DAYS", 2)
        self.request_delay_seconds = _env_float("DAILY_UPDATE_REQUEST_DELAY_SECONDS", 1.2)
        self.update_time = os.getenv("DAILY_UPDATE_TIME", "00:10")
        self.coin_ids = _parse_coin_ids(os.getenv("DAILY_UPDATE_COINS", "bitcoin,ethereum"))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self.running = False
        self.last_run_started_at: str | None = None
        self.last_run_finished_at: str | None = None
        self.last_success_at: str | None = None
        self.last_error: str | None = None
        self.last_created_count = 0
        self.last_skipped_existing = 0
        self.current_total_targets = 0
        self.current_processed_targets = 0
        self.last_state_snapshot_upserts = 0
        self.last_performance_snapshot_upserts = 0
        self.last_composite_snapshot_upserts = 0
        self.last_composite_v2_snapshot_upserts = 0
        self.last_run_duration_seconds = 0.0
        self.last_regime_flow_correlation_90d: float | None = None

    def start(self):
        if not self.enabled:
            logger.info("daily_update.disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="daily-update")
        self._thread.start()
        logger.info(
            "daily_update.started time=%s lookback_days=%s coins=%s",
            self.update_time,
            self.lookback_days,
            ",".join(self.coin_ids),
        )

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("daily_update.stopped")

    def _worker_loop(self):
        if self.run_on_startup:
            self.run_update_once()

        while not self._stop_event.is_set():
            now = datetime.now()
            next_run = self._next_run_datetime(now)
            sleep_seconds = max(1, int((next_run - now).total_seconds()))
            if self._stop_event.wait(timeout=sleep_seconds):
                return
            self.run_update_once()

    def _next_run_datetime(self, now: datetime) -> datetime:
        try:
            hour_str, minute_str = self.update_time.split(":", 1)
            hour = max(0, min(23, int(hour_str)))
            minute = max(0, min(59, int(minute_str)))
        except Exception:
            hour, minute = 0, 10

        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run + timedelta(days=1)
        return next_run

    def run_update_once(self):
        if not self._run_lock.acquire(blocking=False):
            logger.info("daily_update.run_skipped_already_running")
            return False

        db = SessionLocal()
        created_count = 0
        skipped_existing = 0
        state_snapshot_upserts = 0
        performance_snapshot_upserts = 0
        composite_snapshot_upserts = 0
        composite_v2_snapshot_upserts = 0
        run_started_monotonic = time.perf_counter()

        try:
            self.running = True
            self.last_error = None
            self.last_run_started_at = datetime.now(timezone.utc).isoformat()
            cryptos = crud.get_cryptocurrencies(db, skip=0, limit=1000)
            targets = [c for c in cryptos if c.coingecko_id in self.coin_ids]
            self.current_total_targets = len(targets)
            self.current_processed_targets = 0
            logger.info("daily_update.run_start targets=%s", len(targets))

            end_timestamp = datetime.now(timezone.utc)
            start_timestamp = end_timestamp - timedelta(days=self.lookback_days)

            for crypto in targets:
                try:
                    market_chart = cg.get_coin_market_chart_range_by_id(
                        id=crypto.coingecko_id,
                        vs_currency="usd",
                        from_timestamp=str(start_timestamp.timestamp()),
                        to_timestamp=str(end_timestamp.timestamp()),
                    )
                except Exception as exc:
                    logger.warning("daily_update.fetch_error coin=%s error=%s", crypto.coingecko_id, exc)
                    time.sleep(self.request_delay_seconds)
                    continue

                prices = market_chart.get("prices", [])
                market_caps = market_chart.get("market_caps", [])
                total_volumes = market_chart.get("total_volumes", [])
                count = min(len(prices), len(market_caps), len(total_volumes))

                for i in range(count):
                    entry_date = datetime.fromtimestamp(prices[i][0] / 1000, tz=timezone.utc).date()
                    existing = crud.get_price_history_by_crypto_id_and_date(db, crypto_id=crypto.id, date=entry_date)
                    if existing:
                        skipped_existing += 1
                        self.last_created_count = created_count
                        self.last_skipped_existing = skipped_existing
                        continue

                    payload = schemas.PriceHistoryCreate(
                        date=entry_date,
                        price_usd=prices[i][1],
                        market_cap_usd=market_caps[i][1],
                        total_volume_usd=total_volumes[i][1],
                    )
                    crud.create_price_history_entry(db=db, price_data=payload, crypto_id=crypto.id)
                    created_count += 1
                    self.last_created_count = created_count
                    self.last_skipped_existing = skipped_existing

                history = crud.get_price_history_all(db, crypto_id=crypto.id)
                prices = [float(entry.price_usd) for entry in history]
                volumes = [float(entry.total_volume_usd) for entry in history]
                if len(prices) >= 120 and len(volumes) >= 120:
                    try:
                        state = compute_market_state(
                            coingecko_id=crypto.coingecko_id,
                            prices=prices,
                            volumes=volumes,
                        )
                        crud.upsert_market_state_snapshot(
                            db=db,
                            crypto_id=crypto.id,
                            snapshot_date=end_timestamp.date(),
                            state=state,
                        )
                        state_snapshot_upserts += 1
                        self.last_state_snapshot_upserts = state_snapshot_upserts

                        composite = compute_composite_v1(
                            coingecko_id=crypto.coingecko_id,
                            snapshot_date=end_timestamp.date(),
                            state=state,
                            prices=prices,
                            volumes=volumes,
                            horizon_days=30,
                        )
                        crud.upsert_market_composite_snapshot(
                            db=db,
                            crypto_id=crypto.id,
                            snapshot_date=end_timestamp.date(),
                            horizon_days=composite.horizon_days,
                            regime_score=composite.components.regime_score,
                            flow_score=composite.components.flow_score,
                            sentiment_score=composite.components.sentiment_score,
                            composite_score=composite.composite_score,
                            label=composite.label,
                            confidence=composite.confidence,
                            generated_at=composite.generated_at,
                        )
                        composite_snapshot_upserts += 1
                        self.last_composite_snapshot_upserts = composite_snapshot_upserts

                        composite_v2 = compute_composite_v2(
                            coingecko_id=crypto.coingecko_id,
                            snapshot_date=end_timestamp.date(),
                            prices=prices,
                            volumes=volumes,
                            horizon_days=30,
                        )
                        crud.upsert_market_composite_v2_snapshot(
                            db=db,
                            crypto_id=crypto.id,
                            snapshot_date=end_timestamp.date(),
                            horizon_days=composite_v2["horizon_days"],
                            regime_score=composite_v2["components"]["regime_score"],
                            flow_score=composite_v2["components"]["flow_score"],
                            sentiment_score=composite_v2["components"]["sentiment_score"],
                            risk_score=composite_v2["components"]["risk_score"],
                            regime_weight=composite_v2["components"]["weights"]["regime"],
                            flow_weight=composite_v2["components"]["weights"]["flow"],
                            sentiment_weight=composite_v2["components"]["weights"]["sentiment"],
                            risk_weight=composite_v2["components"]["weights"]["risk"],
                            composite_score=composite_v2["composite_score"],
                            label=composite_v2["label"],
                            confidence=composite_v2["confidence"],
                            generated_at=composite_v2["generated_at"],
                        )
                        composite_v2_snapshot_upserts += 1
                        self.last_composite_v2_snapshot_upserts = composite_v2_snapshot_upserts

                        composite_rows = crud.get_market_composite_history(
                            db=db,
                            crypto_id=crypto.id,
                            limit=90,
                        )
                        if len(composite_rows) >= 10:
                            rs = [float(x.regime_score) for x in composite_rows]
                            fs = [float(x.flow_score) for x in composite_rows]
                            corr = _pearson_correlation(rs, fs)
                            self.last_regime_flow_correlation_90d = round(corr, 4) if corr is not None else None
                            logger.info(
                                "daily_update.composite_corr coin=%s window=90 corr=%s",
                                crypto.coingecko_id,
                                self.last_regime_flow_correlation_90d,
                            )
                    except Exception as exc:
                        logger.warning(
                            "daily_update.state_or_composite_error coin=%s error=%s",
                            crypto.coingecko_id,
                            exc,
                        )

                state_rows = crud.get_market_state_history(
                    db=db,
                    crypto_id=crypto.id,
                    start_date=None,
                    end_date=None,
                    limit=5000,
                )
                if state_rows and len(history) > 40:
                    try:
                        probability_by_date = {
                            row.snapshot_date: float(row.probability_up) for row in state_rows
                        }
                        price_by_date = {entry.date: float(entry.price_usd) for entry in history}
                        perf = compute_market_state_performance(
                            probability_by_date=probability_by_date,
                            price_by_date=price_by_date,
                            horizon_days=30,
                        )
                        if perf is not None:
                            crud.upsert_market_state_performance_snapshot(
                                db=db,
                                crypto_id=crypto.id,
                                snapshot_date=end_timestamp.date(),
                                horizon_days=30,
                                samples=perf.samples,
                                directional_accuracy=perf.directional_accuracy,
                                brier_score=perf.brier_score,
                                avg_future_return_pct=perf.avg_future_return_pct,
                                avg_probability_up=perf.avg_probability_up,
                                generated_at=datetime.now(timezone.utc),
                            )
                            performance_snapshot_upserts += 1
                            self.last_performance_snapshot_upserts = performance_snapshot_upserts
                    except Exception as exc:
                        logger.warning(
                            "daily_update.performance_snapshot_error coin=%s error=%s",
                            crypto.coingecko_id,
                            exc,
                        )

                time.sleep(self.request_delay_seconds)
                self.current_processed_targets += 1

            logger.info(
                "daily_update.run_complete created=%s skipped_existing=%s state_snapshot_upserts=%s",
                created_count,
                skipped_existing,
                state_snapshot_upserts,
            )
            self.last_success_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("daily_update.run_failed error=%s", exc)
        finally:
            duration_seconds = round(time.perf_counter() - run_started_monotonic, 3)
            self.last_created_count = created_count
            self.last_skipped_existing = skipped_existing
            self.last_state_snapshot_upserts = state_snapshot_upserts
            self.last_performance_snapshot_upserts = performance_snapshot_upserts
            self.last_composite_snapshot_upserts = composite_snapshot_upserts
            self.last_composite_v2_snapshot_upserts = composite_v2_snapshot_upserts
            self.last_run_duration_seconds = duration_seconds
            self.last_run_finished_at = datetime.now(timezone.utc).isoformat()
            self.running = False
            self.current_total_targets = 0
            self.current_processed_targets = 0
            db.close()
            self._run_lock.release()
            logger.info(
                "daily_update.run_timing duration_seconds=%s performance_snapshot_upserts=%s",
                duration_seconds,
                performance_snapshot_upserts,
            )

        return True

    def trigger_async_update(self) -> bool:
        if self.running:
            return False
        thread = threading.Thread(target=self.run_update_once, daemon=True, name="manual-daily-update")
        thread.start()
        return True

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "update_time": self.update_time,
            "coin_ids": self.coin_ids,
            "lookback_days": self.lookback_days,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "last_created_count": self.last_created_count,
            "last_skipped_existing": self.last_skipped_existing,
            "last_state_snapshot_upserts": self.last_state_snapshot_upserts,
            "last_performance_snapshot_upserts": self.last_performance_snapshot_upserts,
            "last_composite_snapshot_upserts": self.last_composite_snapshot_upserts,
            "last_composite_v2_snapshot_upserts": self.last_composite_v2_snapshot_upserts,
            "last_run_duration_seconds": self.last_run_duration_seconds,
            "last_regime_flow_correlation_90d": self.last_regime_flow_correlation_90d,
            "current_total_targets": self.current_total_targets,
            "current_processed_targets": self.current_processed_targets,
        }
