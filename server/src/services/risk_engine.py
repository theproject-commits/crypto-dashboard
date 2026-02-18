from __future__ import annotations

import math


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


def compute_risk_score_v2(prices: list[float]) -> dict:
    if len(prices) < 90:
        raise ValueError("Insufficient history for risk v2 (need >=90 points)")

    returns_7 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 6, len(prices))
        if prices[i - 1] > 0
    ]
    returns_30 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 29, len(prices))
        if prices[i - 1] > 0
    ]

    vol_7 = _stddev(returns_7) * 100.0
    vol_30 = _stddev(returns_30) * 100.0

    atr_7 = sum(abs(x) for x in returns_7) / len(returns_7) if returns_7 else 0.0
    atr_30 = sum(abs(x) for x in returns_30) / len(returns_30) if returns_30 else 0.0
    atr_expansion = (atr_7 / atr_30) if atr_30 > 0 else 1.0

    drawdown_60 = _max_drawdown_pct(prices[-60:])
    drawdown_180 = _max_drawdown_pct(prices[-180:]) if len(prices) >= 180 else drawdown_60

    risk_score = _clamp(
        30.0 * (vol_7 / 8.0)
        + 20.0 * (vol_30 / 10.0)
        + 25.0 * (max(0.0, atr_expansion - 1.0) / 1.2)
        + 15.0 * (abs(drawdown_60) / 20.0)
        + 10.0 * (abs(drawdown_180) / 35.0),
        0.0,
        100.0,
    )

    if risk_score >= 75.0:
        risk_state = "high_risk"
    elif risk_score <= 35.0:
        risk_state = "low_risk"
    else:
        risk_state = "medium_risk"

    volatility_event_flag = bool(atr_expansion >= 1.7 and vol_7 >= 5.0)

    return {
        "score": round(risk_score, 2),
        "risk_state": risk_state,
        "volatility_event_flag": volatility_event_flag,
        "components": {
            "volatility_7d_pct": round(vol_7, 4),
            "volatility_30d_pct": round(vol_30, 4),
            "atr_expansion_ratio": round(atr_expansion, 4),
            "drawdown_60d_pct": round(drawdown_60, 4),
            "drawdown_180d_pct": round(drawdown_180, 4),
        },
    }
