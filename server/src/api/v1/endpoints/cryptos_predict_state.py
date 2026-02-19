from datetime import UTC, date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .... import crud, schemas
from ....database import get_db
from ....security import require_auth
from ....services.market_state_engine import compute_market_state
from .cryptos_utils import (
    clamp as _clamp,
    future_returns_by_snapshot_date as _future_returns_by_snapshot_date,
    max_drawdown_pct as _max_drawdown_pct,
    normalize_probabilities as _normalize_probabilities,
    rsi as _rsi,
    sma as _sma,
    stddev as _stddev,
)

router = APIRouter()


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
