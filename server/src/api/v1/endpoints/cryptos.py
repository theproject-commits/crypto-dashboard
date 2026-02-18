from datetime import UTC, datetime
import html as html_lib
import math
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pycoingecko import CoinGeckoAPI
import requests
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date

from .... import crud, schemas
from ....database import get_db
from ....security import require_auth
from ....services.composite_engine import compute_composite_v1
from ....services.composite_v2_engine import compute_composite_v2
from ....services.market_state_engine import compute_market_state

router = APIRouter()
cg = CoinGeckoAPI()


def _sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(values) - period, len(values)):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += abs(diff)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - (100 / (1 + rs))


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _max_drawdown_pct(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            dd = ((value - peak) / peak) * 100.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _normalize_probabilities(p_up: float, p_flat: float, p_down: float) -> tuple[float, float, float]:
    p_up = max(0.001, p_up)
    p_flat = max(0.001, p_flat)
    p_down = max(0.001, p_down)
    total = p_up + p_flat + p_down
    return p_up / total, p_flat / total, p_down / total


def _future_returns_by_snapshot_date(
    price_by_date: dict[date, float],
    horizon_days: int = 30,
) -> dict[date, float]:
    target_dates = sorted(price_by_date.keys())
    returns: dict[date, float] = {}
    for idx, current_date in enumerate(target_dates):
        target_idx = idx + horizon_days
        if target_idx >= len(target_dates):
            continue
        current_price = price_by_date.get(current_date)
        future_price = price_by_date.get(target_dates[target_idx])
        if current_price is None or future_price is None or current_price <= 0:
            continue
        returns[current_date] = ((future_price - current_price) / current_price) * 100.0
    return returns


def _clean_html_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _future_window_metrics_by_snapshot_date(
    price_by_date: dict[date, float],
    horizon_days: int = 30,
) -> dict[date, tuple[float, float]]:
    target_dates = sorted(price_by_date.keys())
    metrics: dict[date, tuple[float, float]] = {}
    for idx, current_date in enumerate(target_dates):
        target_idx = idx + horizon_days
        if target_idx >= len(target_dates):
            continue
        current_price = price_by_date.get(current_date)
        if current_price is None or current_price <= 0:
            continue
        future_dates = target_dates[idx + 1 : target_idx + 1]
        if not future_dates:
            continue
        future_prices = [price_by_date[d] for d in future_dates if d in price_by_date]
        if not future_prices:
            continue
        final_price = future_prices[-1]
        ret_30 = ((final_price - current_price) / current_price) * 100.0
        min_future = min(future_prices)
        drawdown_30 = ((min_future - current_price) / current_price) * 100.0
        metrics[current_date] = (ret_30, drawdown_30)
    return metrics


def _aggregate_segment(segment: str, values: list[tuple[float, float]]) -> schemas.ResearchSegmentMetrics:
    if not values:
        return schemas.ResearchSegmentMetrics(segment=segment, samples=0)
    returns = [x[0] for x in values]
    drawdowns = [x[1] for x in values]
    directional_hits = sum(1 for r in returns if r > 0)
    return schemas.ResearchSegmentMetrics(
        segment=segment,
        samples=len(values),
        avg_return_30d_pct=round(sum(returns) / len(returns), 6),
        return_std_30d_pct=round(_stddev(returns), 6),
        avg_drawdown_30d_pct=round(sum(drawdowns) / len(drawdowns), 6),
        worst_drawdown_30d_pct=round(min(drawdowns), 6),
        directional_accuracy=round(directional_hits / len(returns), 6),
    )


def _max_drawdown_from_returns(returns_pct: list[float]) -> float:
    if not returns_pct:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1.0 + (r / 100.0))
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = ((equity - peak) / peak) * 100.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _aggregate_backtest_segment(
    segment: str,
    returns_pct: list[float],
    horizon_days: int,
) -> schemas.BacktestV2Segment:
    if not returns_pct:
        return schemas.BacktestV2Segment(segment=segment, samples=0)
    samples = len(returns_pct)
    avg_return = sum(returns_pct) / samples
    return_std = _stddev(returns_pct)
    hit_rate = sum(1 for r in returns_pct if r > 0) / samples
    if return_std > 0:
        sharpe = (avg_return / return_std) * math.sqrt(365.0 / float(horizon_days))
    else:
        sharpe = 0.0
    max_dd = _max_drawdown_from_returns(returns_pct)
    return schemas.BacktestV2Segment(
        segment=segment,
        samples=samples,
        avg_return_pct=round(avg_return, 6),
        return_std_pct=round(return_std, 6),
        hit_rate=round(hit_rate, 6),
        sharpe=round(sharpe, 6),
        max_drawdown_pct=round(max_dd, 6),
    )


def _policy_zone(score: float, lower_threshold: float, upper_threshold: float) -> str:
    if score <= lower_threshold:
        return "risk_off"
    if score >= upper_threshold:
        return "risk_on"
    return "neutral"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _to_year_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _compute_walk_forward_month_metrics(
    rows: list[tuple[date, float, float]],
    lower_threshold: float,
    upper_threshold: float,
    horizon_days: int,
) -> tuple[int, int, float | None, float | None, float | None, float | None, float | None]:
    if not rows:
        return 0, 0, None, None, None, None, None

    future_returns = [x[2] for x in rows]
    strategy_returns: list[float] = []
    active_signals = 0
    hit_count = 0
    for _, score, future_return in rows:
        if score >= upper_threshold:
            strategy_returns.append(future_return)
            active_signals += 1
            if future_return > 0:
                hit_count += 1
        elif score <= lower_threshold:
            strategy_returns.append(-future_return)
            active_signals += 1
            if future_return < 0:
                hit_count += 1
        else:
            strategy_returns.append(0.0)

    avg_future_return = sum(future_returns) / len(future_returns) if future_returns else None
    avg_strategy_return = sum(strategy_returns) / len(strategy_returns) if strategy_returns else None
    hit_rate = (hit_count / active_signals) if active_signals > 0 else None
    std_strategy = _stddev(strategy_returns)
    sharpe = ((avg_strategy_return / std_strategy) * math.sqrt(365.0 / float(horizon_days))) if std_strategy > 0 else None
    max_dd = _max_drawdown_from_returns(strategy_returns)
    return (
        len(rows),
        active_signals,
        avg_future_return,
        avg_strategy_return,
        hit_rate,
        sharpe,
        max_dd,
    )

@router.post("/", response_model=schemas.Cryptocurrency)
def create_cryptocurrency(
    crypto: schemas.CryptocurrencyCreate,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=crypto.coingecko_id)
    if db_crypto:
        raise HTTPException(status_code=400, detail="Cryptocurrency with this CoinGecko ID already registered")
    return crud.create_cryptocurrency(db=db, crypto=crypto)

@router.get("/", response_model=List[schemas.Cryptocurrency])
def read_cryptocurrencies(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    cryptos = crud.get_cryptocurrencies(db, skip=skip, limit=limit)
    return cryptos

@router.get("/{coingecko_id}", response_model=schemas.Cryptocurrency)
def read_cryptocurrency(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")
    return db_crypto


@router.get("/{coingecko_id}/profile", response_model=schemas.CryptoProfileResponse)
def read_crypto_profile(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    try:
        response = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coingecko_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return schemas.CryptoProfileResponse(
            coingecko_id=coingecko_id,
            name=db_crypto.name,
            symbol=db_crypto.symbol.lower(),
            description="Descricao detalhada indisponivel no momento. O provedor externo nao respondeu.",
            homepage=None,
            genesis_date=None,
            categories=[],
        )

    description = _clean_html_text((payload.get("description") or {}).get("en"))
    if not description:
        description = "Descricao indisponivel no provedor."

    homepage_list = (payload.get("links") or {}).get("homepage") or []
    homepage = next((x for x in homepage_list if isinstance(x, str) and x.strip()), None)
    categories = [str(x) for x in (payload.get("categories") or []) if isinstance(x, str)]

    return schemas.CryptoProfileResponse(
        coingecko_id=coingecko_id,
        name=str(payload.get("name") or db_crypto.name),
        symbol=str(payload.get("symbol") or db_crypto.symbol).lower(),
        description=description,
        homepage=homepage,
        genesis_date=payload.get("genesis_date"),
        categories=categories[:12],
    )

@router.get("/{coingecko_id}/history", response_model=List[schemas.PriceHistory])
def read_price_history(
    coingecko_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    if start_date is None and end_date is None:
        return crud.get_price_history_all(db, crypto_id=db_crypto.id)

    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="Provide both start_date and end_date, or neither.")

    return crud.get_price_history(db, crypto_id=db_crypto.id, start_date=start_date, end_date=end_date)

@router.post("/{coingecko_id}/populate-history")
def populate_history_endpoint(
    coingecko_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found in database. Cannot populate history.")
    
    success = crud.populate_price_history_from_coingecko(db, coingecko_id, days)
    if success:
        return {"message": f"Successfully populated {coingecko_id} history for {days} days."}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to populate {coingecko_id} history. Check CoinGecko ID or API limits.")


@router.get("/{coingecko_id}/live", response_model=schemas.LivePriceResponse)
def read_live_price(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    provider_price: float | None = None
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        response = requests.get(
            url,
            params={"ids": coingecko_id, "vs_currencies": "usd"},
            timeout=4,
        )
        response.raise_for_status()
        payload = response.json()
        if payload and coingecko_id in payload and "usd" in payload[coingecko_id]:
            provider_price = float(payload[coingecko_id]["usd"])
    except Exception:
        provider_price = None

    if provider_price is not None:
        return schemas.LivePriceResponse(
            coingecko_id=coingecko_id,
            price_usd=provider_price,
            fetched_at=datetime.now(UTC),
            source="coingecko",
        )

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    if not history:
        raise HTTPException(status_code=502, detail="Live provider unavailable and no local history fallback")

    fallback_price = float(history[-1].price_usd)
    return schemas.LivePriceResponse(
        coingecko_id=coingecko_id,
        price_usd=fallback_price,
        fetched_at=datetime.now(UTC),
        source="fallback_history",
    )


@router.get("/{coingecko_id}/predict", response_model=schemas.PredictResponse)
def predict_price_direction(
    coingecko_id: str,
    horizon: str = Query(default="24h", pattern="^(24h|7d|30d|180d|365d)$"),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    if len(history) < 60:
        raise HTTPException(status_code=400, detail="Insufficient history for prediction (need at least 60 points)")

    prices = [float(entry.price_usd) for entry in history]
    volumes = [float(entry.total_volume_usd) for entry in history]
    last_price = prices[-1]

    sma_20 = _sma(prices, 20)
    sma_50 = _sma(prices, 50)
    rsi_14 = _rsi(prices, 14)
    if sma_20 is None or sma_50 is None or rsi_14 is None:
        raise HTTPException(status_code=400, detail="Insufficient data for indicators")

    momentum_14d = ((last_price - prices[-15]) / prices[-15]) * 100 if prices[-15] > 0 else 0.0
    momentum_30d = ((last_price - prices[-31]) / prices[-31]) * 100 if prices[-31] > 0 else 0.0
    returns_30 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 29, len(prices))
        if prices[i - 1] > 0
    ]
    volatility_30d = _stddev(returns_30) * 100
    volume_slice = volumes[-30:]
    avg_volume = sum(volume_slice) / len(volume_slice)
    volume_std = _stddev(volume_slice) or 1.0
    volume_zscore_30 = (volumes[-1] - avg_volume) / volume_std

    trend_short = (last_price - sma_20) / sma_20
    trend_mid = (sma_20 - sma_50) / sma_50
    rsi_norm = (rsi_14 - 50.0) / 50.0
    mom14_norm = momentum_14d / 20.0
    mom30_norm = momentum_30d / 30.0
    vol_norm = volatility_30d / 10.0
    volume_norm = volume_zscore_30 / 2.5

    if horizon == "24h":
        score = (
            0.28 * trend_short
            + 0.20 * rsi_norm
            + 0.22 * mom14_norm
            + 0.12 * volume_norm
            + 0.10 * trend_mid
            - 0.16 * vol_norm
        )
    elif horizon == "7d":
        score = (
            0.30 * trend_mid
            + 0.24 * trend_short
            + 0.18 * mom30_norm
            + 0.14 * rsi_norm
            + 0.08 * volume_norm
            - 0.12 * vol_norm
        )
    elif horizon == "30d":
        score = (
            0.34 * trend_mid
            + 0.22 * trend_short
            + 0.20 * mom30_norm
            + 0.14 * rsi_norm
            + 0.06 * volume_norm
            - 0.10 * vol_norm
        )
    elif horizon == "180d":
        score = (
            0.42 * trend_mid
            + 0.20 * trend_short
            + 0.16 * mom30_norm
            + 0.14 * rsi_norm
            + 0.04 * volume_norm
            - 0.08 * vol_norm
        )
    else:  # 365d
        score = (
            0.48 * trend_mid
            + 0.18 * trend_short
            + 0.14 * mom30_norm
            + 0.14 * rsi_norm
            + 0.02 * volume_norm
            - 0.06 * vol_norm
        )

    score = _clamp(score, -1.0, 1.0)
    probability_up = _clamp(0.5 + (score * 0.33), 0.05, 0.95)
    confidence = abs(probability_up - 0.5) * 2

    if probability_up >= 0.66:
        signal = "strong_buy"
    elif probability_up >= 0.56:
        signal = "buy"
    elif probability_up <= 0.34:
        signal = "strong_sell"
    elif probability_up <= 0.44:
        signal = "sell"
    else:
        signal = "neutral"

    return schemas.PredictResponse(
        coingecko_id=coingecko_id,
        horizon=horizon,
        signal=signal,
        probability_up=round(probability_up, 4),
        confidence=round(confidence, 4),
        generated_at=datetime.now(UTC),
        last_price_usd=round(last_price, 8),
        features=schemas.PredictFeatures(
            momentum_14d_pct=round(momentum_14d, 4),
            momentum_30d_pct=round(momentum_30d, 4),
            volatility_30d_pct=round(volatility_30d, 4),
            rsi_14=round(rsi_14, 4),
            sma_20=round(sma_20, 8),
            sma_50=round(sma_50, 8),
            volume_zscore_30=round(volume_zscore_30, 4),
        ),
    )


@router.get("/{coingecko_id}/state", response_model=schemas.MarketStateResponse)
def read_market_state(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    prices = [float(entry.price_usd) for entry in history]
    volumes = [float(entry.total_volume_usd) for entry in history]
    try:
        state = compute_market_state(coingecko_id=coingecko_id, prices=prices, volumes=volumes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return state


@router.get("/{coingecko_id}/state/history", response_model=List[schemas.MarketStateSnapshotResponse])
def read_market_state_history(
    coingecko_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(default=365, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_state_history(
        db,
        crypto_id=db_crypto.id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    if not rows:
        return []

    snapshots = list(reversed(rows))
    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_returns = _future_returns_by_snapshot_date(price_by_date=price_by_date, horizon_days=30)

    output: list[schemas.MarketStateSnapshotResponse] = []
    for row in snapshots:
        future_return_30d_pct = future_returns.get(row.snapshot_date)
        output.append(
            schemas.MarketStateSnapshotResponse(
                snapshot_date=row.snapshot_date,
                regime=row.regime,
                probability_up=float(row.probability_up),
                probability_flat=float(row.probability_flat),
                probability_down=float(row.probability_down),
                risk_score=float(row.risk_score),
                asymmetry_score=float(row.asymmetry_score),
                momentum_structural_score=float(row.momentum_structural_score),
                volatility_future_7d_pct=float(row.volatility_future_7d_pct),
                volatility_future_30d_pct=float(row.volatility_future_30d_pct),
                confidence=float(row.confidence),
                last_price_usd=float(row.last_price_usd),
                future_return_30d_pct=round(future_return_30d_pct, 6) if future_return_30d_pct is not None else None,
            )
        )
    return output


@router.get(
    "/{coingecko_id}/state/performance",
    response_model=schemas.MarketStatePerformanceSnapshotResponse,
)
def read_market_state_performance(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_state_performance_history(
        db=db,
        crypto_id=db_crypto.id,
        horizon_days=horizon_days,
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No performance snapshot found")
    row = rows[0]
    return schemas.MarketStatePerformanceSnapshotResponse(
        snapshot_date=row.snapshot_date,
        horizon_days=row.horizon_days,
        samples=row.samples,
        directional_accuracy=float(row.directional_accuracy),
        brier_score=float(row.brier_score),
        avg_future_return_pct=float(row.avg_future_return_pct) if row.avg_future_return_pct is not None else None,
        avg_probability_up=float(row.avg_probability_up),
        generated_at=row.generated_at,
    )


@router.get(
    "/{coingecko_id}/state/performance/history",
    response_model=List[schemas.MarketStatePerformanceSnapshotResponse],
)
def read_market_state_performance_history(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(default=365, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_state_performance_history(
        db=db,
        crypto_id=db_crypto.id,
        horizon_days=horizon_days,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    output: list[schemas.MarketStatePerformanceSnapshotResponse] = []
    for row in reversed(rows):
        output.append(
            schemas.MarketStatePerformanceSnapshotResponse(
                snapshot_date=row.snapshot_date,
                horizon_days=row.horizon_days,
                samples=row.samples,
                directional_accuracy=float(row.directional_accuracy),
                brier_score=float(row.brier_score),
                avg_future_return_pct=float(row.avg_future_return_pct) if row.avg_future_return_pct is not None else None,
                avg_probability_up=float(row.avg_probability_up),
                generated_at=row.generated_at,
            )
        )
    return output


@router.get("/{coingecko_id}/composite", response_model=schemas.CompositeResponse)
def read_composite_score(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_composite_history(
        db=db,
        crypto_id=db_crypto.id,
        limit=1,
    )
    if rows:
        row = rows[0]
        return schemas.CompositeResponse(
            coingecko_id=coingecko_id,
            snapshot_date=row.snapshot_date,
            horizon_days=row.horizon_days,
            composite_score=float(row.composite_score),
            label=row.label,
            confidence=float(row.confidence),
            generated_at=row.generated_at,
            components=schemas.CompositeComponents(
                regime_score=float(row.regime_score),
                flow_score=float(row.flow_score),
                sentiment_score=float(row.sentiment_score),
                sentiment_source="baseline",
            ),
        )

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    prices = [float(entry.price_usd) for entry in history]
    volumes = [float(entry.total_volume_usd) for entry in history]
    if len(prices) < 120 or len(volumes) < 120:
        raise HTTPException(status_code=400, detail="Insufficient history for composite score")
    state = compute_market_state(coingecko_id=coingecko_id, prices=prices, volumes=volumes)
    return compute_composite_v1(
        coingecko_id=coingecko_id,
        snapshot_date=history[-1].date,
        state=state,
        prices=prices,
        volumes=volumes,
        horizon_days=30,
    )


@router.get("/{coingecko_id}/composite/history", response_model=List[schemas.CompositeSnapshotResponse])
def read_composite_history(
    coingecko_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(default=365, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_composite_history(
        db=db,
        crypto_id=db_crypto.id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    output: list[schemas.CompositeSnapshotResponse] = []
    for row in reversed(rows):
        output.append(
            schemas.CompositeSnapshotResponse(
                snapshot_date=row.snapshot_date,
                horizon_days=row.horizon_days,
                regime_score=float(row.regime_score),
                flow_score=float(row.flow_score),
                sentiment_score=float(row.sentiment_score),
                composite_score=float(row.composite_score),
                label=row.label,
                confidence=float(row.confidence),
                generated_at=row.generated_at,
            )
        )
    return output


@router.get("/{coingecko_id}/composite/v2", response_model=schemas.CompositeV2Response)
def read_composite_score_v2(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    prices = [float(entry.price_usd) for entry in history]
    volumes = [float(entry.total_volume_usd) for entry in history]
    if len(prices) < 180 or len(volumes) < 60:
        raise HTTPException(status_code=400, detail="Insufficient history for composite v2")

    snapshot_date = history[-1].date
    computed = compute_composite_v2(
        coingecko_id=coingecko_id,
        snapshot_date=snapshot_date,
        prices=prices,
        volumes=volumes,
        horizon_days=horizon_days,
    )
    crud.upsert_market_composite_v2_snapshot(
        db=db,
        crypto_id=db_crypto.id,
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
        regime_score=computed["components"]["regime_score"],
        flow_score=computed["components"]["flow_score"],
        sentiment_score=computed["components"]["sentiment_score"],
        risk_score=computed["components"]["risk_score"],
        regime_weight=computed["components"]["weights"]["regime"],
        flow_weight=computed["components"]["weights"]["flow"],
        sentiment_weight=computed["components"]["weights"]["sentiment"],
        risk_weight=computed["components"]["weights"]["risk"],
        composite_score=computed["composite_score"],
        label=computed["label"],
        confidence=computed["confidence"],
        generated_at=computed["generated_at"],
    )
    return computed


@router.get(
    "/{coingecko_id}/composite/interpretation",
    response_model=schemas.CompositeInterpretationResponse,
)
def read_composite_interpretation(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    lower_threshold: float = Query(default=20.0, ge=0.0, le=100.0),
    upper_threshold: float = Query(default=60.0, ge=0.0, le=100.0),
    min_train_months: int = Query(default=12, ge=3, le=36),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    if lower_threshold >= upper_threshold:
        raise HTTPException(status_code=400, detail="lower_threshold must be < upper_threshold")

    v1 = read_composite_score(coingecko_id=coingecko_id, db=db, _user=_user)
    v2 = read_composite_score_v2(coingecko_id=coingecko_id, horizon_days=horizon_days, db=db, _user=_user)
    v2_history = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id).id,
        horizon_days=horizon_days,
        limit=8,
    )

    walk_forward = None
    try:
        walk_forward = read_composite_v2_walk_forward(
            coingecko_id=coingecko_id,
            horizon_days=horizon_days,
            min_train_months=min_train_months,
            lower_threshold=lower_threshold,
            upper_threshold=upper_threshold,
            limit=5000,
            db=db,
            _user=_user,
        )
    except HTTPException:
        walk_forward = None

    comp = v2["components"]
    regime_score = float(comp["regime_score"])
    flow_score = float(comp["flow_score"])
    risk_score = float(comp["risk_score"])
    sentiment_score = comp["sentiment_score"]
    flow_quality = str(comp["flow"]["quality"])
    sentiment_quality = str(comp["sentiment"]["quality"])

    reasons: list[str] = []
    if regime_score < 40:
        reasons.append(f"Regime estrutural fraco ({regime_score:.1f}) pressiona o contexto.")
    elif regime_score > 60:
        reasons.append(f"Regime estrutural favoravel ({regime_score:.1f}) sustenta contexto positivo.")
    else:
        reasons.append(f"Regime estrutural intermediario ({regime_score:.1f}) sem dominancia clara.")

    if flow_score < 45:
        reasons.append(f"Flow abaixo do neutro ({flow_score:.1f}) com qualidade {flow_quality}.")
    elif flow_score > 55:
        reasons.append(f"Flow acima do neutro ({flow_score:.1f}) com qualidade {flow_quality}.")
    else:
        reasons.append(f"Flow neutro ({flow_score:.1f}) com qualidade {flow_quality}.")

    if risk_score > 55:
        reasons.append(f"Risk elevado ({risk_score:.1f}) aumenta probabilidade de instabilidade.")
    elif risk_score < 35:
        reasons.append(f"Risk baixo ({risk_score:.1f}) reduz probabilidade de whipsaw.")
    else:
        reasons.append(f"Risk moderado ({risk_score:.1f}) exige disciplina de risco.")

    if sentiment_score is None:
        reasons.append(f"Sentimento indisponivel ({sentiment_quality}); peso redistribuido automaticamente.")
    else:
        reasons.append(f"Sentimento em {float(sentiment_score):.1f} ({sentiment_quality}).")

    reasons = reasons[:3]

    alerts: list[str] = []
    score_gap = float(v2["composite_score"]) - float(v1.composite_score)
    if abs(score_gap) >= 15:
        alerts.append(
            f"Divergencia relevante v1/v2: v1={float(v1.composite_score):.1f}, v2={float(v2['composite_score']):.1f}."
        )
    if flow_quality != "derivatives_plus_spot":
        alerts.append(f"Flow com fallback de qualidade ({flow_quality}).")
    if sentiment_quality != "external":
        alerts.append(f"Sentimento sem fonte externa completa ({sentiment_quality}).")

    if len(v2_history) >= 2:
        latest = float(v2_history[0].composite_score)
        prev = float(v2_history[1].composite_score)
        delta_1 = latest - prev
        if abs(delta_1) >= 8:
            alerts.append(f"Mudanca diaria forte no v2 ({delta_1:+.1f} pontos).")

    zone = _policy_zone(score=float(v2["composite_score"]), lower_threshold=lower_threshold, upper_threshold=upper_threshold)
    if zone == "risk_off":
        policy_implication = (
            f"Score v2 em zona risk-off (<= {lower_threshold:.0f}); leitura de defesa pela policy objetiva."
        )
    elif zone == "risk_on":
        policy_implication = (
            f"Score v2 em zona risk-on (>= {upper_threshold:.0f}); leitura de contexto construtivo pela policy objetiva."
        )
    else:
        policy_implication = (
            f"Score v2 em zona neutra ({lower_threshold:.0f}-{upper_threshold:.0f}); sem vantagem direcional forte."
        )

    if walk_forward is not None:
        if walk_forward.total_test_samples > 0:
            wf_hit = _format_pct((walk_forward.overall_hit_rate or 0) * 100)
            wf_sharpe = (
                f"{walk_forward.overall_sharpe:.3f}" if walk_forward.overall_sharpe is not None else "N/A"
            )
            wf_coverage = (walk_forward.total_active_signals / walk_forward.total_test_samples) * 100
            reliability = (
                f"Confianca interna {float(v2['confidence']) * 100:.1f}% | "
                f"WF {horizon_days}D hit-rate {wf_hit} sharpe {wf_sharpe} coverage {wf_coverage:.1f}%."
            )
        else:
            reliability = f"Confianca interna {float(v2['confidence']) * 100:.1f}% | walk-forward sem amostra ativa."
    else:
        reliability = f"Confianca interna {float(v2['confidence']) * 100:.1f}% | walk-forward indisponivel."

    summary = (
        f"{zone.replace('_', ' ').title()}: v2 {float(v2['composite_score']):.1f} ({v2['label']}) "
        f"vs v1 {float(v1.composite_score):.1f} ({v1.label})."
    )

    return schemas.CompositeInterpretationResponse(
        coingecko_id=coingecko_id,
        generated_at=datetime.now(UTC),
        horizon_days=horizon_days,
        lower_threshold=lower_threshold,
        upper_threshold=upper_threshold,
        v1_score=round(float(v1.composite_score), 4),
        v1_label=v1.label,
        v2_score=round(float(v2["composite_score"]), 4),
        v2_label=str(v2["label"]),
        summary=summary,
        reasons=reasons,
        reliability=reliability,
        policy_implication=policy_implication,
        alerts=alerts[:4],
        guardrails=[
            "Interpretacao de contexto; nao e recomendacao de compra/venda.",
            "Nao projeta preco futuro nem define tamanho de posicao.",
            "Qualquer decisao deve seguir policy objetiva e controle de risco.",
        ],
    )


@router.get("/{coingecko_id}/composite/v2/history", response_model=List[schemas.CompositeV2SnapshotResponse])
def read_composite_v2_history(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(default=365, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=db_crypto.id,
        horizon_days=horizon_days,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    output: list[schemas.CompositeV2SnapshotResponse] = []
    for row in reversed(rows):
        output.append(
            schemas.CompositeV2SnapshotResponse(
                snapshot_date=row.snapshot_date,
                horizon_days=row.horizon_days,
                regime_score=float(row.regime_score),
                flow_score=float(row.flow_score),
                sentiment_score=float(row.sentiment_score) if row.sentiment_score is not None else None,
                risk_score=float(row.risk_score),
                regime_weight=float(row.regime_weight),
                flow_weight=float(row.flow_weight),
                sentiment_weight=float(row.sentiment_weight),
                risk_weight=float(row.risk_weight),
                composite_score=float(row.composite_score),
                label=row.label,
                confidence=float(row.confidence),
                generated_at=row.generated_at,
            )
        )
    return output


@router.get(
    "/{coingecko_id}/composite/v2/research/backtest",
    response_model=schemas.CompositeV2BacktestResponse,
)
def read_composite_v2_backtest(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=2000, ge=50, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    if len(history) < horizon_days + 30:
        raise HTTPException(status_code=400, detail="Insufficient price history for backtest")
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_metrics = _future_window_metrics_by_snapshot_date(price_by_date, horizon_days=horizon_days)

    rows = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=db_crypto.id,
        horizon_days=horizon_days,
        limit=limit,
    )

    bucket_returns: dict[str, list[float]] = {
        "<30": [],
        "30-45": [],
        "45-55": [],
        "55-70": [],
        ">=70": [],
    }
    regime_returns: dict[str, list[float]] = {
        "bullish_trend_low_risk": [],
        "bullish_trend_high_risk": [],
        "bearish_trend_low_risk": [],
        "bearish_trend_high_risk": [],
        "transition_compression": [],
        "volatility_event_regime": [],
    }
    ordered_regimes = [
        "bullish_trend_low_risk",
        "bullish_trend_high_risk",
        "bearish_trend_low_risk",
        "bearish_trend_high_risk",
        "transition_compression",
        "volatility_event_regime",
    ]

    if not rows:
        bucket_segments = [
            _aggregate_backtest_segment(segment=k, returns_pct=v, horizon_days=horizon_days)
            for k, v in bucket_returns.items()
        ]
        regime_segments = [
            _aggregate_backtest_segment(segment=k, returns_pct=regime_returns.get(k, []), horizon_days=horizon_days)
            for k in ordered_regimes
        ]
        return schemas.CompositeV2BacktestResponse(
            coingecko_id=coingecko_id,
            horizon_days=horizon_days,
            generated_at=datetime.now(UTC),
            total_samples=0,
            bucket_segments=bucket_segments,
            regime_segments=regime_segments,
        )

    total_samples = 0
    for row in rows:
        metrics = future_metrics.get(row.snapshot_date)
        if metrics is None:
            continue
        future_return = float(metrics[0])
        total_samples += 1
        score = float(row.composite_score)
        if score < 30:
            bucket_returns["<30"].append(future_return)
        elif score < 45:
            bucket_returns["30-45"].append(future_return)
        elif score < 55:
            bucket_returns["45-55"].append(future_return)
        elif score < 70:
            bucket_returns["55-70"].append(future_return)
        else:
            bucket_returns[">=70"].append(future_return)

        regime_key = str(row.label)
        if regime_key not in regime_returns:
            regime_returns[regime_key] = []
        regime_returns[regime_key].append(future_return)

    bucket_segments = [
        _aggregate_backtest_segment(segment=k, returns_pct=v, horizon_days=horizon_days)
        for k, v in bucket_returns.items()
    ]
    regime_segments = [
        _aggregate_backtest_segment(segment=k, returns_pct=regime_returns.get(k, []), horizon_days=horizon_days)
        for k in ordered_regimes
    ]
    extra_regimes = sorted(set(regime_returns.keys()) - set(ordered_regimes))
    for key in extra_regimes:
        regime_segments.append(
            _aggregate_backtest_segment(
                segment=key,
                returns_pct=regime_returns.get(key, []),
                horizon_days=horizon_days,
            )
        )

    return schemas.CompositeV2BacktestResponse(
        coingecko_id=coingecko_id,
        horizon_days=horizon_days,
        generated_at=datetime.now(UTC),
        total_samples=total_samples,
        bucket_segments=bucket_segments,
        regime_segments=regime_segments,
    )


@router.get(
    "/{coingecko_id}/composite/v2/research/walk-forward",
    response_model=schemas.CompositeV2WalkForwardResponse,
)
def read_composite_v2_walk_forward(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    min_train_months: int = Query(default=12, ge=3, le=36),
    lower_threshold: float = Query(default=30.0, ge=0.0, le=100.0),
    upper_threshold: float = Query(default=70.0, ge=0.0, le=100.0),
    limit: int = Query(default=5000, ge=200, le=20000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    if lower_threshold >= upper_threshold:
        raise HTTPException(status_code=400, detail="lower_threshold must be < upper_threshold")

    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    if len(history) < horizon_days + 120:
        raise HTTPException(status_code=400, detail="Insufficient price history for walk-forward")
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_metrics = _future_window_metrics_by_snapshot_date(price_by_date, horizon_days=horizon_days)

    snapshots = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=db_crypto.id,
        horizon_days=horizon_days,
        limit=limit,
    )
    aligned_rows: list[tuple[date, float, float]] = []
    for row in reversed(snapshots):
        metrics = future_metrics.get(row.snapshot_date)
        if metrics is None:
            continue
        aligned_rows.append((row.snapshot_date, float(row.composite_score), float(metrics[0])))

    if len(aligned_rows) < 120:
        raise HTTPException(status_code=404, detail="Not enough aligned composite v2 rows for walk-forward")

    rows_by_month: dict[str, list[tuple[date, float, float]]] = {}
    for item in aligned_rows:
        month_key = _to_year_month(item[0])
        rows_by_month.setdefault(month_key, []).append(item)
    ordered_months = sorted(rows_by_month.keys())
    if len(ordered_months) <= min_train_months:
        raise HTTPException(status_code=404, detail="Not enough monthly windows for walk-forward")

    month_results: list[schemas.WalkForwardMonthResult] = []
    overall_future_returns: list[float] = []
    overall_strategy_returns: list[float] = []
    overall_active = 0
    overall_hits = 0

    for idx in range(min_train_months, len(ordered_months)):
        train_months = ordered_months[:idx]
        test_month = ordered_months[idx]
        train_rows = [row for m in train_months for row in rows_by_month.get(m, [])]
        test_rows = rows_by_month.get(test_month, [])
        if not test_rows:
            continue

        test_count, active_signals, avg_future_return, avg_strategy_return, hit_rate, sharpe, max_dd = (
            _compute_walk_forward_month_metrics(
                rows=test_rows,
                lower_threshold=lower_threshold,
                upper_threshold=upper_threshold,
                horizon_days=horizon_days,
            )
        )

        ge70_returns = [ret for _, score, ret in test_rows if score >= 70.0]
        lt30_returns = [ret for _, score, ret in test_rows if score < 30.0]
        ge70_avg = (sum(ge70_returns) / len(ge70_returns)) if ge70_returns else None
        lt30_avg = (sum(lt30_returns) / len(lt30_returns)) if lt30_returns else None

        for _, score, ret in test_rows:
            overall_future_returns.append(ret)
            if score >= upper_threshold:
                overall_strategy_returns.append(ret)
                overall_active += 1
                if ret > 0:
                    overall_hits += 1
            elif score <= lower_threshold:
                overall_strategy_returns.append(-ret)
                overall_active += 1
                if ret < 0:
                    overall_hits += 1
            else:
                overall_strategy_returns.append(0.0)

        month_results.append(
            schemas.WalkForwardMonthResult(
                month=test_month,
                train_samples=len(train_rows),
                test_samples=test_count,
                active_signals=active_signals,
                avg_future_return_pct=round(avg_future_return, 6) if avg_future_return is not None else None,
                avg_strategy_return_pct=round(avg_strategy_return, 6) if avg_strategy_return is not None else None,
                hit_rate=round(hit_rate, 6) if hit_rate is not None else None,
                sharpe=round(sharpe, 6) if sharpe is not None else None,
                max_drawdown_pct=round(max_dd, 6) if max_dd is not None else None,
                bucket_ge70_avg_return_pct=round(ge70_avg, 6) if ge70_avg is not None else None,
                bucket_lt30_avg_return_pct=round(lt30_avg, 6) if lt30_avg is not None else None,
            )
        )

    overall_avg_future = (
        (sum(overall_future_returns) / len(overall_future_returns)) if overall_future_returns else None
    )
    overall_avg_strategy = (
        (sum(overall_strategy_returns) / len(overall_strategy_returns)) if overall_strategy_returns else None
    )
    overall_hit_rate = (overall_hits / overall_active) if overall_active > 0 else None
    overall_std = _stddev(overall_strategy_returns)
    overall_sharpe = (
        ((overall_avg_strategy / overall_std) * math.sqrt(365.0 / float(horizon_days)))
        if overall_avg_strategy is not None and overall_std > 0
        else None
    )
    overall_max_dd = _max_drawdown_from_returns(overall_strategy_returns) if overall_strategy_returns else None

    return schemas.CompositeV2WalkForwardResponse(
        coingecko_id=coingecko_id,
        horizon_days=horizon_days,
        lower_threshold=lower_threshold,
        upper_threshold=upper_threshold,
        min_train_months=min_train_months,
        generated_at=datetime.now(UTC),
        total_test_samples=len(overall_strategy_returns),
        total_active_signals=overall_active,
        overall_avg_future_return_pct=round(overall_avg_future, 6) if overall_avg_future is not None else None,
        overall_avg_strategy_return_pct=round(overall_avg_strategy, 6) if overall_avg_strategy is not None else None,
        overall_hit_rate=round(overall_hit_rate, 6) if overall_hit_rate is not None else None,
        overall_sharpe=round(overall_sharpe, 6) if overall_sharpe is not None else None,
        overall_max_drawdown_pct=round(overall_max_dd, 6) if overall_max_dd is not None else None,
        months=month_results,
    )


@router.get(
    "/{coingecko_id}/composite/research/buckets",
    response_model=schemas.CompositeBucketStudyResponse,
)
def read_composite_bucket_study(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=2000, ge=50, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_metrics = _future_window_metrics_by_snapshot_date(price_by_date, horizon_days=horizon_days)
    rows = crud.get_market_composite_history(db=db, crypto_id=db_crypto.id, limit=limit)

    buckets: dict[str, list[tuple[float, float]]] = {
        "<30": [],
        "30-45": [],
        "45-55": [],
        "55-70": [],
        ">=70": [],
    }
    for row in rows:
        m = future_metrics.get(row.snapshot_date)
        if m is None:
            continue
        score = float(row.composite_score)
        if score < 30:
            buckets["<30"].append(m)
        elif score < 45:
            buckets["30-45"].append(m)
        elif score < 55:
            buckets["45-55"].append(m)
        elif score < 70:
            buckets["55-70"].append(m)
        else:
            buckets[">=70"].append(m)

    segments = [_aggregate_segment(k, v) for k, v in buckets.items()]
    return schemas.CompositeBucketStudyResponse(
        coingecko_id=coingecko_id,
        horizon_days=horizon_days,
        generated_at=datetime.now(UTC),
        segments=segments,
    )


@router.get(
    "/{coingecko_id}/state/research/regime-consistency",
    response_model=schemas.RegimeConsistencyResponse,
)
def read_regime_consistency(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=2000, ge=50, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_metrics = _future_window_metrics_by_snapshot_date(price_by_date, horizon_days=horizon_days)
    rows = crud.get_market_state_history(db=db, crypto_id=db_crypto.id, limit=limit)

    grouped: dict[str, list[tuple[float, float]]] = {
        "bearish_trend": [],
        "compression_range": [],
        "transition": [],
        "bullish_trend": [],
    }
    for row in rows:
        m = future_metrics.get(row.snapshot_date)
        if m is None:
            continue
        grouped.setdefault(row.regime, []).append(m)

    ordered_keys = ["bearish_trend", "compression_range", "transition", "bullish_trend"]
    segments = [_aggregate_segment(k, grouped[k]) for k in ordered_keys]
    return schemas.RegimeConsistencyResponse(
        coingecko_id=coingecko_id,
        horizon_days=horizon_days,
        generated_at=datetime.now(UTC),
        segments=segments,
    )


@router.get(
    "/{coingecko_id}/composite/research/confidence",
    response_model=schemas.ConfidenceCalibrationResponse,
)
def read_confidence_calibration(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=2000, ge=50, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_metrics = _future_window_metrics_by_snapshot_date(price_by_date, horizon_days=horizon_days)
    rows = crud.get_market_composite_history(db=db, crypto_id=db_crypto.id, limit=limit)

    buckets: dict[str, list[tuple[float, float]]] = {
        "<0.40": [],
        "0.40-0.60": [],
        ">0.60": [],
    }
    for row in rows:
        m = future_metrics.get(row.snapshot_date)
        if m is None:
            continue
        conf = float(row.confidence)
        if conf < 0.40:
            buckets["<0.40"].append(m)
        elif conf <= 0.60:
            buckets["0.40-0.60"].append(m)
        else:
            buckets[">0.60"].append(m)

    segments = [_aggregate_segment(k, v) for k, v in buckets.items()]
    return schemas.ConfidenceCalibrationResponse(
        coingecko_id=coingecko_id,
        horizon_days=horizon_days,
        generated_at=datetime.now(UTC),
        segments=segments,
    )
