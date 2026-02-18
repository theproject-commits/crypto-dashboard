from __future__ import annotations

from datetime import UTC, date, datetime

from .flow_engine import compute_flow_score_v2
from .regime_engine_v2 import compute_regime_v2
from .risk_engine import compute_risk_score_v2
from .sentiment_engine import compute_sentiment_score_v2


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weighted_average(parts: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in parts)
    if total_weight <= 0:
        return 50.0
    return sum(value * weight for value, weight in parts) / total_weight


def _normalize_weights(raw: dict[str, float], available: dict[str, bool]) -> dict[str, float]:
    active = {k: v for k, v in raw.items() if available.get(k, False)}
    total = sum(active.values())
    if total <= 0:
        return {"regime": 0.0, "flow": 0.0, "sentiment": 0.0, "risk": 0.0}
    normalized = {k: (v / total) for k, v in active.items()}
    return {
        "regime": normalized.get("regime", 0.0),
        "flow": normalized.get("flow", 0.0),
        "sentiment": normalized.get("sentiment", 0.0),
        "risk": normalized.get("risk", 0.0),
    }


def _label_from_context(regime: str, risk_state: str, volatility_event_flag: bool) -> str:
    if volatility_event_flag:
        return "volatility_event_regime"
    if regime == "bullish_trend" and risk_state == "low_risk":
        return "bullish_trend_low_risk"
    if regime == "bullish_trend" and risk_state != "low_risk":
        return "bullish_trend_high_risk"
    if regime == "bearish_trend" and risk_state == "low_risk":
        return "bearish_trend_low_risk"
    if regime == "bearish_trend" and risk_state != "low_risk":
        return "bearish_trend_high_risk"
    return "transition_compression"


def compute_composite_v2(
    coingecko_id: str,
    snapshot_date: date,
    prices: list[float],
    volumes: list[float],
    horizon_days: int = 30,
    include_external: bool = True,
) -> dict:
    regime = compute_regime_v2(prices=prices, volumes=volumes)
    flow = compute_flow_score_v2(
        coingecko_id=coingecko_id,
        prices=prices,
        volumes=volumes,
        include_external=include_external,
    )
    sentiment = compute_sentiment_score_v2(coingecko_id=coingecko_id, include_external=include_external)
    risk = compute_risk_score_v2(prices=prices)

    base_weights = {
        "regime": 0.30,
        "flow": 0.30,
        "sentiment": 0.20,
        "risk": 0.20,
    }
    available = {
        "regime": True,
        "flow": True,
        "sentiment": sentiment.get("score") is not None,
        "risk": True,
    }
    weights = _normalize_weights(base_weights, available)

    risk_supportive = 100.0 - float(risk["score"])
    pieces = [
        (float(regime["score"]), weights["regime"]),
        (float(flow["score"]), weights["flow"]),
        (risk_supportive, weights["risk"]),
    ]
    if available["sentiment"]:
        pieces.append((float(sentiment["score"]), weights["sentiment"]))

    composite_score = _clamp(_weighted_average(pieces), 0.0, 100.0)
    label = _label_from_context(
        regime=regime["regime"],
        risk_state=risk["risk_state"],
        volatility_event_flag=bool(risk["volatility_event_flag"]),
    )
    confidence = _clamp(
        0.5 * (abs(composite_score - 50.0) / 50.0)
        + 0.3 * (1.0 - min(float(risk["score"]) / 100.0, 1.0))
        + 0.2 * (1.0 if flow["quality"] == "derivatives_plus_spot" else 0.6),
        0.0,
        1.0,
    )

    return {
        "coingecko_id": coingecko_id,
        "snapshot_date": snapshot_date,
        "horizon_days": horizon_days,
        "composite_score": round(composite_score, 2),
        "label": label,
        "confidence": round(confidence, 4),
        "generated_at": datetime.now(UTC),
        "components": {
            "regime_score": float(regime["score"]),
            "flow_score": float(flow["score"]),
            "sentiment_score": float(sentiment["score"]) if sentiment.get("score") is not None else None,
            "risk_score": float(risk["score"]),
            "weights": {
                "regime": round(weights["regime"], 4),
                "flow": round(weights["flow"], 4),
                "sentiment": round(weights["sentiment"], 4),
                "risk": round(weights["risk"], 4),
            },
            "regime": regime,
            "flow": flow,
            "sentiment": sentiment,
            "risk": risk,
        },
    }
