from __future__ import annotations

import math
from datetime import UTC, datetime

from .. import schemas


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(values: list[float], period: int = 14) -> float | None:
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


def compute_market_state(
    coingecko_id: str,
    prices: list[float],
    volumes: list[float],
) -> schemas.MarketStateResponse:
    if len(prices) < 120 or len(volumes) < 120:
        raise ValueError("Insufficient history for market state (need at least 120 points)")

    last_price = prices[-1]
    sma20 = _sma(prices, 20)
    sma50 = _sma(prices, 50)
    rsi14 = _rsi(prices, 14)
    if sma20 is None or sma50 is None or rsi14 is None:
        raise ValueError("Insufficient data for indicators")

    momentum_30d = ((last_price - prices[-31]) / prices[-31]) * 100 if prices[-31] > 0 else 0.0
    momentum_90d = ((last_price - prices[-91]) / prices[-91]) * 100 if prices[-91] > 0 else 0.0
    sma_spread_pct = ((sma20 - sma50) / sma50) * 100 if sma50 > 0 else 0.0
    returns_30 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 29, len(prices))
        if prices[i - 1] > 0
    ]
    volatility_30d = _stddev(returns_30) * 100
    drawdown_180d = _max_drawdown_pct(prices[-180:])

    volume_slice = volumes[-30:]
    avg_volume = sum(volume_slice) / len(volume_slice)
    volume_std = _stddev(volume_slice) or 1.0
    volume_zscore_30 = (volumes[-1] - avg_volume) / volume_std

    trend_core = (
        0.34 * (sma_spread_pct / 8.0)
        + 0.28 * (momentum_30d / 12.0)
        + 0.22 * (momentum_90d / 25.0)
        + 0.10 * ((rsi14 - 50.0) / 25.0)
        + 0.06 * (volume_zscore_30 / 2.5)
        - 0.14 * (volatility_30d / 12.0)
        - 0.12 * (abs(drawdown_180d) / 45.0)
    )
    trend_core = _clamp(trend_core, -1.0, 1.0)

    probability_up = _clamp(0.5 + trend_core * 0.34, 0.05, 0.90)
    probability_flat = _clamp(0.58 - abs(trend_core) * 0.62 - (volatility_30d / 48.0), 0.06, 0.70)
    remainder = max(0.03, 1.0 - probability_flat)
    probability_up = _clamp(probability_up * remainder, 0.03, 0.94)
    probability_down = max(0.03, 1.0 - probability_flat - probability_up)
    probability_up, probability_flat, probability_down = _normalize_probabilities(
        probability_up, probability_flat, probability_down
    )

    if volatility_30d < 2.2 and abs(momentum_30d) < 3.5:
        regime = "compression_range"
    elif sma20 > sma50 and momentum_30d > 0:
        regime = "bullish_trend"
    elif sma20 < sma50 and momentum_30d < 0:
        regime = "bearish_trend"
    else:
        regime = "transition"

    risk_score = _clamp(
        34.0 * (volatility_30d / 12.0)
        + 34.0 * (abs(drawdown_180d) / 45.0)
        + 32.0 * probability_down,
        0.0,
        100.0,
    )
    asymmetry_score = _clamp(
        50.0
        + (probability_up - probability_down) * 44.0
        + (momentum_90d / 25.0) * 10.0
        - (volatility_30d / 16.0) * 8.0,
        0.0,
        100.0,
    )
    momentum_structural_score = _clamp(
        50.0 + sma_spread_pct * 3.0 + momentum_90d * 0.8 + (rsi14 - 50.0) * 0.6,
        0.0,
        100.0,
    )

    volatility_future_7d = _clamp(
        volatility_30d * math.sqrt(7.0 / 30.0) * (0.85 + abs(momentum_30d) / 120.0),
        0.1,
        40.0,
    )
    volatility_future_30d = _clamp(
        volatility_30d * (0.92 + abs(momentum_90d) / 220.0),
        0.1,
        80.0,
    )
    confidence = _clamp(
        abs(probability_up - probability_down) * 0.72 + abs(0.34 - probability_flat) * 0.28,
        0.0,
        1.0,
    )

    return schemas.MarketStateResponse(
        coingecko_id=coingecko_id,
        regime=regime,
        probability_up=round(probability_up, 4),
        probability_flat=round(probability_flat, 4),
        probability_down=round(probability_down, 4),
        risk_score=round(risk_score, 2),
        asymmetry_score=round(asymmetry_score, 2),
        momentum_structural_score=round(momentum_structural_score, 2),
        volatility_future_7d_pct=round(volatility_future_7d, 4),
        volatility_future_30d_pct=round(volatility_future_30d, 4),
        confidence=round(confidence, 4),
        generated_at=datetime.now(UTC),
        last_price_usd=round(last_price, 8),
        components=schemas.MarketStateComponents(
            momentum_30d_pct=round(momentum_30d, 4),
            momentum_90d_pct=round(momentum_90d, 4),
            sma20_sma50_spread_pct=round(sma_spread_pct, 4),
            rsi_14=round(rsi14, 4),
            volatility_30d_pct=round(volatility_30d, 4),
            drawdown_180d_pct=round(drawdown_180d, 4),
            volume_zscore_30=round(volume_zscore_30, 4),
        ),
    )
