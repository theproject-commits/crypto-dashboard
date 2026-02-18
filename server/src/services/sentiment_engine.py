from __future__ import annotations

import requests


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _fetch_fear_greed() -> float | None:
    response = requests.get(
        "https://api.alternative.me/fng/",
        params={"limit": 1, "format": "json"},
        timeout=6,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or []
    if not data:
        return None
    raw = data[0].get("value")
    if raw is None:
        return None
    return float(raw)


def _fetch_coingecko_trending_rank(coingecko_id: str) -> int | None:
    response = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=6)
    response.raise_for_status()
    payload = response.json()
    coins = payload.get("coins") or []
    for idx, entry in enumerate(coins, start=1):
        item = entry.get("item") or {}
        if str(item.get("id", "")).lower() == coingecko_id.lower():
            return idx
    return None


def compute_sentiment_score_v2(coingecko_id: str, include_external: bool = True) -> dict:
    if not include_external:
        return {
            "score": None,
            "quality": "disabled_backfill",
            "components": {
                "fear_greed": None,
                "trending_rank": None,
                "sources_used": [],
                "errors": [],
            },
        }

    metrics: list[tuple[str, float, float]] = []
    errors: list[str] = []

    fear_greed = None
    try:
        fear_greed = _fetch_fear_greed()
        if fear_greed is not None:
            metrics.append(("fear_greed", _clamp(fear_greed, 0.0, 100.0), 0.75))
    except Exception as exc:
        errors.append(f"fear_greed_unavailable:{exc.__class__.__name__}")

    trending_rank = None
    try:
        trending_rank = _fetch_coingecko_trending_rank(coingecko_id=coingecko_id)
        if trending_rank is not None:
            trending_score = 100.0 - ((trending_rank - 1) * 6.0)
            metrics.append(("coingecko_trending", _clamp(trending_score, 20.0, 100.0), 0.25))
    except Exception as exc:
        errors.append(f"trending_unavailable:{exc.__class__.__name__}")

    if not metrics:
        return {
            "score": None,
            "quality": "unavailable",
            "components": {
                "fear_greed": fear_greed,
                "trending_rank": trending_rank,
                "sources_used": [],
                "errors": errors,
            },
        }

    total_weight = sum(w for _, _, w in metrics)
    score = sum(value * weight for _, value, weight in metrics) / total_weight

    return {
        "score": round(_clamp(score, 0.0, 100.0), 2),
        "quality": "external",
        "components": {
            "fear_greed": round(fear_greed, 2) if fear_greed is not None else None,
            "trending_rank": trending_rank,
            "sources_used": [name for name, _, _ in metrics],
            "errors": errors,
        },
    }
