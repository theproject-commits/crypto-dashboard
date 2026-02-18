from __future__ import annotations

import math

from ..providers.binance_derivatives import (
    fetch_funding_rate_series,
    fetch_open_interest_hist_series,
)


COIN_SYMBOL_MAP = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
    "ripple": "XRPUSDT",
    "cardano": "ADAUSDT",
    "dogecoin": "DOGEUSDT",
    "binancecoin": "BNBUSDT",
}


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pct_change(newer: float, older: float) -> float | None:
    if older == 0:
        return None
    return ((newer - older) / older) * 100.0


def _cvd_proxy(prices: list[float], volumes: list[float], window: int = 14) -> float:
    start = max(1, len(prices) - window)
    cvd = 0.0
    for i in range(start, len(prices)):
        direction = 1.0 if prices[i] >= prices[i - 1] else -1.0
        cvd += direction * volumes[i]
    vol_scale = sum(volumes[start:]) or 1.0
    return (cvd / vol_scale) * 100.0


def compute_flow_score_v2(
    coingecko_id: str,
    prices: list[float],
    volumes: list[float],
    include_external: bool = True,
) -> dict:
    if len(prices) < 35 or len(volumes) < 35:
        raise ValueError("Insufficient history for flow v2 (need >=35 points)")

    symbol = COIN_SYMBOL_MAP.get(coingecko_id)

    oi_delta_7d = None
    funding_avg = None
    oi_price_divergence = None
    derivatives_available = False
    derivatives_errors: list[str] = []

    if include_external and symbol:
        try:
            oi_rows = fetch_open_interest_hist_series(symbol=symbol, period="1d", limit=15)
            if len(oi_rows) >= 8:
                recent = oi_rows[-1]["sum_open_interest"]
                prior = oi_rows[-8]["sum_open_interest"]
                oi_delta_7d = _pct_change(recent, prior)
                derivatives_available = True
        except Exception as exc:
            derivatives_errors.append(f"oi_unavailable:{exc.__class__.__name__}")

        try:
            funding_rows = fetch_funding_rate_series(symbol=symbol, limit=42)
            if funding_rows:
                funding_avg = sum(row["funding_rate"] for row in funding_rows) / len(funding_rows)
                derivatives_available = True
        except Exception as exc:
            derivatives_errors.append(f"funding_unavailable:{exc.__class__.__name__}")

    price_delta_7d = _pct_change(prices[-1], prices[-8]) if len(prices) >= 8 else 0.0
    if oi_delta_7d is not None and price_delta_7d is not None:
        oi_price_divergence = oi_delta_7d - price_delta_7d

    cvd_14 = _cvd_proxy(prices=prices, volumes=volumes, window=14)

    returns_7 = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - 6, len(prices))
        if prices[i - 1] > 0
    ]
    vol_7 = _stddev(returns_7) * 100.0
    vol_window = volumes[-30:]
    avg_vol = sum(vol_window) / len(vol_window)
    std_vol = _stddev(vol_window) or 1.0
    volume_z = (volumes[-1] - avg_vol) / std_vol

    base_score = 50.0 + (cvd_14 * 0.35) + (volume_z * 6.5) - (vol_7 * 1.1)

    if derivatives_available:
        if oi_delta_7d is not None:
            base_score += oi_delta_7d * 0.9
        if funding_avg is not None:
            base_score += (funding_avg * 10000.0) * 0.5
        if oi_price_divergence is not None:
            base_score += oi_price_divergence * 0.4

    flow_score = _clamp(base_score, 0.0, 100.0)

    if derivatives_available:
        quality = "derivatives_plus_spot"
    elif not include_external:
        quality = "spot_only_backfill"
    elif symbol:
        quality = "spot_only"
    else:
        quality = "spot_only_unmapped_symbol"

    return {
        "score": round(flow_score, 2),
        "quality": quality,
        "components": {
            "symbol": symbol,
            "oi_delta_7d_pct": round(oi_delta_7d, 4) if oi_delta_7d is not None else None,
            "funding_avg": round(funding_avg, 8) if funding_avg is not None else None,
            "oi_price_divergence": round(oi_price_divergence, 4) if oi_price_divergence is not None else None,
            "cvd_proxy_14": round(cvd_14, 4),
            "price_delta_7d_pct": round(price_delta_7d, 4) if price_delta_7d is not None else None,
            "volume_zscore_30": round(volume_z, 4),
            "volatility_7d_pct": round(vol_7, 4),
            "derivatives_available": derivatives_available,
            "derivatives_errors": derivatives_errors,
        },
    }
