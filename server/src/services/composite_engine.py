from __future__ import annotations

from datetime import UTC, date, datetime
import math

from .. import schemas


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _label_from_score(score: float) -> str:
    if score >= 70.0:
        return "bullish_high_conviction"
    if score >= 55.0:
        return "bullish_moderate"
    if score >= 45.0:
        return "neutral_transition"
    if score >= 30.0:
        return "bearish_moderate"
    return "bearish_high_risk"


def _regime_score_from_state(state: schemas.MarketStateResponse) -> float:
    momentum = float(state.momentum_structural_score)
    if state.regime == "bullish_trend":
        return 85.0 if momentum >= 65.0 else 70.0
    if state.regime == "bearish_trend":
        return 15.0 if momentum <= 35.0 else 30.0
    if state.regime == "compression_range":
        return 50.0
    return 50.0


def compute_composite_v1(
    coingecko_id: str,
    snapshot_date: date,
    state: schemas.MarketStateResponse,
    prices: list[float],
    volumes: list[float],
    horizon_days: int = 30,
) -> schemas.CompositeResponse:
    if len(prices) < 35 or len(volumes) < 35:
        raise ValueError("Insufficient history for composite score (need at least 35 points)")

    regime_score = _clamp(_regime_score_from_state(state), 0.0, 100.0)

    returns_7 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 6, len(prices))
        if prices[i - 1] > 0
    ]
    vol_7 = _stddev(returns_7) * 100.0
    vol_series_30 = volumes[-30:]
    avg_vol = sum(vol_series_30) / len(vol_series_30)
    std_vol = _stddev(vol_series_30) or 1.0
    vol_z = (volumes[-1] - avg_vol) / std_vol
    mom_7 = ((prices[-1] - prices[-8]) / prices[-8]) * 100.0 if prices[-8] > 0 else 0.0

    flow_proxy = 50.0 + (mom_7 * 1.2) + (vol_z * 8.0) - (vol_7 * 0.9)
    flow_score = _clamp(flow_proxy, 0.0, 100.0)

    sentiment_score = 50.0

    composite_score = (
        0.40 * regime_score
        + 0.35 * flow_score
        + 0.25 * sentiment_score
    )
    composite_score = _clamp(composite_score, 0.0, 100.0)
    label = _label_from_score(composite_score)
    confidence = _clamp(
        0.35 * abs(state.probability_up - state.probability_down)
        + 0.65 * (abs(composite_score - 50.0) / 50.0),
        0.0,
        1.0,
    )

    return schemas.CompositeResponse(
        coingecko_id=coingecko_id,
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
        composite_score=round(composite_score, 2),
        label=label,
        confidence=round(confidence, 4),
        generated_at=datetime.now(UTC),
        components=schemas.CompositeComponents(
            regime_score=round(regime_score, 2),
            flow_score=round(flow_score, 2),
            sentiment_score=round(sentiment_score, 2),
            sentiment_source="baseline",
        ),
    )
