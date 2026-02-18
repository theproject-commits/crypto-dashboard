from __future__ import annotations

import math


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def _linear_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = 0.0
    den = 0.0
    for i, y in enumerate(values):
        dx = i - x_mean
        num += dx * (y - y_mean)
        den += dx * dx
    if den == 0:
        return 0.0
    return num / den


def compute_regime_v2(prices: list[float], volumes: list[float]) -> dict:
    if len(prices) < 180 or len(volumes) < 60:
        raise ValueError("Insufficient history for regime v2 (need >=180 prices and >=60 volumes)")

    last_price = prices[-1]
    sma20 = _sma(prices, 20)
    sma50 = _sma(prices, 50)
    if sma20 is None or sma50 is None:
        raise ValueError("Insufficient data for SMA indicators")
    rsi14 = _rsi(prices, 14)
    if rsi14 is None:
        raise ValueError("Insufficient data for RSI")

    momentum_30d = ((last_price - prices[-31]) / prices[-31]) * 100 if prices[-31] > 0 else 0.0
    momentum_90d = ((last_price - prices[-91]) / prices[-91]) * 100 if prices[-91] > 0 else 0.0

    returns_30 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 29, len(prices))
        if prices[i - 1] > 0
    ]
    volatility_30d = _stddev(returns_30) * 100
    drawdown_180d = _max_drawdown_pct(prices[-180:])

    vol_slice = volumes[-30:]
    vol_mean = sum(vol_slice) / len(vol_slice)
    vol_std = _stddev(vol_slice) or 1.0
    volume_zscore_30 = (volumes[-1] - vol_mean) / vol_std

    sma_spread_pct = ((sma20 - sma50) / sma50) * 100 if sma50 > 0 else 0.0
    sma50_series = [(sum(prices[i - 49 : i + 1]) / 50.0) for i in range(len(prices) - 30, len(prices))]
    sma50_slope = _linear_slope(sma50_series)
    sma50_slope_pct = (sma50_slope / sma50) * 100 if sma50 > 0 else 0.0
    price_distance_sma50_pct = ((last_price - sma50) / sma50) * 100 if sma50 > 0 else 0.0

    atr_proxy_7 = sum(abs(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(len(prices) - 6, len(prices)) if prices[i - 1] > 0) / 6
    atr_proxy_30 = sum(abs(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(len(prices) - 29, len(prices)) if prices[i - 1] > 0) / 29
    atr_compression_ratio = atr_proxy_7 / atr_proxy_30 if atr_proxy_30 > 0 else 1.0

    score = (
        0.20 * (50.0 + sma_spread_pct * 3.0)
        + 0.18 * (50.0 + momentum_30d * 1.2)
        + 0.15 * (50.0 + momentum_90d * 0.8)
        + 0.10 * (50.0 + (rsi14 - 50.0) * 1.4)
        + 0.08 * (50.0 + volume_zscore_30 * 10.0)
        + 0.10 * (50.0 + sma50_slope_pct * 12.0)
        + 0.09 * (50.0 + price_distance_sma50_pct * 2.5)
        - 0.06 * (volatility_30d * 4.0)
        - 0.04 * (abs(drawdown_180d) * 1.2)
        - 0.10 * (max(0.0, atr_compression_ratio - 1.0) * 20.0)
    )
    regime_score = _clamp(score, 0.0, 100.0)

    if atr_compression_ratio >= 1.6 and volatility_30d >= 5.0:
        regime = "volatility_event_regime"
    elif volatility_30d < 2.2 and abs(momentum_30d) < 3.5 and atr_compression_ratio <= 0.95:
        regime = "transition_compression"
    elif sma20 > sma50 and momentum_30d > 0 and sma50_slope >= 0:
        regime = "bullish_trend"
    elif sma20 < sma50 and momentum_30d < 0 and sma50_slope <= 0:
        regime = "bearish_trend"
    else:
        regime = "transition_compression"

    return {
        "score": round(regime_score, 2),
        "regime": regime,
        "components": {
            "momentum_30d_pct": round(momentum_30d, 4),
            "momentum_90d_pct": round(momentum_90d, 4),
            "sma20_sma50_spread_pct": round(sma_spread_pct, 4),
            "rsi_14": round(rsi14, 4),
            "volatility_30d_pct": round(volatility_30d, 4),
            "drawdown_180d_pct": round(drawdown_180d, 4),
            "volume_zscore_30": round(volume_zscore_30, 4),
            "sma50_slope_pct": round(sma50_slope_pct, 6),
            "price_distance_sma50_pct": round(price_distance_sma50_pct, 4),
            "atr_compression_ratio": round(atr_compression_ratio, 4),
        },
    }
