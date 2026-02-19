from datetime import UTC, date, datetime
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .... import crud, schemas
from ....database import get_db
from ....security import require_auth
from .cryptos_utils import (
    aggregate_backtest_segment as _aggregate_backtest_segment,
    aggregate_segment as _aggregate_segment,
    compute_walk_forward_month_metrics as _compute_walk_forward_month_metrics,
    future_window_metrics_by_snapshot_date as _future_window_metrics_by_snapshot_date,
    max_drawdown_from_returns as _max_drawdown_from_returns,
    stddev as _stddev,
    to_year_month as _to_year_month,
)

router = APIRouter()


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
