from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Dict, List

import requests


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
ONE_DAY_MS = 24 * 60 * 60 * 1000


def _to_ms(d: date) -> int:
    dt = datetime.combine(d, time.min, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_daily_history(
    symbol: str,
    start_date: date,
    end_date: date | None = None,
    timeout_seconds: int = 20,
) -> List[Dict[str, float]]:
    """
    Fetch full daily history using Binance klines pagination.

    Returns rows with:
    - date
    - price_usd (daily close)
    - total_volume_usd (quote asset volume)
    """
    if end_date is None:
        end_date = date.today()

    start_ms = _to_ms(start_date)
    end_ms = _to_ms(end_date) + ONE_DAY_MS - 1
    rows: List[Dict[str, float]] = []

    session = requests.Session()
    while start_ms <= end_ms:
        params = {
            "symbol": symbol,
            "interval": "1d",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1000,
        }
        response = session.get(BINANCE_KLINES_URL, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        klines = response.json()
        if not klines:
            break

        for kline in klines:
            open_time = int(kline[0])
            close_price = float(kline[4])
            quote_volume = float(kline[7])
            row_date = date.fromtimestamp(open_time / 1000)
            rows.append(
                {
                    "date": row_date,
                    "price_usd": close_price,
                    "total_volume_usd": quote_volume,
                }
            )

        start_ms = int(klines[-1][0]) + ONE_DAY_MS

    return rows
