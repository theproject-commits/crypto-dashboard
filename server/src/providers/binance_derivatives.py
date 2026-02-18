from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests


BINANCE_SPOT_BASE = "https://api.binance.com"
BINANCE_FUTURES_BASE = "https://fapi.binance.com"


def fetch_funding_rate_series(symbol: str, limit: int = 90, timeout_seconds: int = 8) -> list[dict[str, Any]]:
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/fundingRate"
    response = requests.get(url, params={"symbol": symbol, "limit": limit}, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []
    for item in payload:
        ts = int(item.get("fundingTime", 0))
        rows.append(
            {
                "funding_rate": float(item.get("fundingRate", 0.0)),
                "funding_time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
            }
        )
    return rows


def fetch_open_interest_hist_series(
    symbol: str,
    period: str = "1d",
    limit: int = 30,
    timeout_seconds: int = 8,
) -> list[dict[str, Any]]:
    url = f"{BINANCE_FUTURES_BASE}/futures/data/openInterestHist"
    response = requests.get(
        url,
        params={"symbol": symbol, "period": period, "limit": limit},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []
    for item in payload:
        ts = int(item.get("timestamp", 0))
        rows.append(
            {
                "sum_open_interest": float(item.get("sumOpenInterest", 0.0)),
                "sum_open_interest_value": float(item.get("sumOpenInterestValue", 0.0)),
                "timestamp": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
            }
        )
    return rows


def fetch_current_open_interest(symbol: str, timeout_seconds: int = 8) -> float:
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/openInterest"
    response = requests.get(url, params={"symbol": symbol}, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    return float(payload.get("openInterest", 0.0))
