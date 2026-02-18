from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class MarketStatePerformanceMetrics:
    samples: int
    directional_accuracy: float
    brier_score: float
    avg_future_return_pct: float | None
    avg_probability_up: float


def _future_return(price_now: float | None, price_future: float | None) -> float | None:
    if price_now is None or price_future is None or price_now <= 0:
        return None
    return ((price_future - price_now) / price_now) * 100.0


def compute_market_state_performance(
    probability_by_date: dict[date, float],
    price_by_date: dict[date, float],
    horizon_days: int = 30,
) -> MarketStatePerformanceMetrics | None:
    target_dates = sorted(price_by_date.keys())
    idx_by_date = {d: i for i, d in enumerate(target_dates)}

    probs: list[float] = []
    outcomes: list[int] = []
    returns: list[float] = []

    for d, p_up in probability_by_date.items():
        idx = idx_by_date.get(d)
        if idx is None:
            continue
        target_idx = idx + horizon_days
        if target_idx >= len(target_dates):
            continue

        current_price = price_by_date.get(d)
        future_price = price_by_date.get(target_dates[target_idx])
        ret = _future_return(current_price, future_price)
        if ret is None:
            continue

        outcome_up = 1 if ret > 0 else 0
        probs.append(float(p_up))
        outcomes.append(outcome_up)
        returns.append(ret)

    if not probs:
        return None

    sample_count = len(probs)
    correct = 0
    brier_sum = 0.0
    for prob, actual in zip(probs, outcomes):
        predicted = 1 if prob >= 0.5 else 0
        if predicted == actual:
            correct += 1
        brier_sum += (prob - actual) ** 2

    avg_return = sum(returns) / len(returns) if returns else None
    avg_prob_up = sum(probs) / len(probs)

    return MarketStatePerformanceMetrics(
        samples=sample_count,
        directional_accuracy=(correct / sample_count),
        brier_score=(brier_sum / sample_count),
        avg_future_return_pct=avg_return,
        avg_probability_up=avg_prob_up,
    )
