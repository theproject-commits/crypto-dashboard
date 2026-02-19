from __future__ import annotations

from datetime import date
import html as html_lib
import math
import re

from .... import schemas


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values: list[float], period: int = 14) -> float | None:
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


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def max_drawdown_pct(values: list[float]) -> float:
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


def normalize_probabilities(p_up: float, p_flat: float, p_down: float) -> tuple[float, float, float]:
    p_up = max(0.001, p_up)
    p_flat = max(0.001, p_flat)
    p_down = max(0.001, p_down)
    total = p_up + p_flat + p_down
    return p_up / total, p_flat / total, p_down / total


def future_returns_by_snapshot_date(
    price_by_date: dict[date, float],
    horizon_days: int = 30,
) -> dict[date, float]:
    target_dates = sorted(price_by_date.keys())
    returns: dict[date, float] = {}
    for idx, current_date in enumerate(target_dates):
        target_idx = idx + horizon_days
        if target_idx >= len(target_dates):
            continue
        current_price = price_by_date.get(current_date)
        future_price = price_by_date.get(target_dates[target_idx])
        if current_price is None or future_price is None or current_price <= 0:
            continue
        returns[current_date] = ((future_price - current_price) / current_price) * 100.0
    return returns


def clean_html_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def future_window_metrics_by_snapshot_date(
    price_by_date: dict[date, float],
    horizon_days: int = 30,
) -> dict[date, tuple[float, float]]:
    target_dates = sorted(price_by_date.keys())
    metrics: dict[date, tuple[float, float]] = {}
    for idx, current_date in enumerate(target_dates):
        target_idx = idx + horizon_days
        if target_idx >= len(target_dates):
            continue
        current_price = price_by_date.get(current_date)
        if current_price is None or current_price <= 0:
            continue
        future_dates = target_dates[idx + 1 : target_idx + 1]
        if not future_dates:
            continue
        future_prices = [price_by_date[d] for d in future_dates if d in price_by_date]
        if not future_prices:
            continue
        final_price = future_prices[-1]
        ret_30 = ((final_price - current_price) / current_price) * 100.0
        min_future = min(future_prices)
        drawdown_30 = ((min_future - current_price) / current_price) * 100.0
        metrics[current_date] = (ret_30, drawdown_30)
    return metrics


def aggregate_segment(segment: str, values: list[tuple[float, float]]) -> schemas.ResearchSegmentMetrics:
    if not values:
        return schemas.ResearchSegmentMetrics(segment=segment, samples=0)
    returns = [x[0] for x in values]
    drawdowns = [x[1] for x in values]
    directional_hits = sum(1 for r in returns if r > 0)
    return schemas.ResearchSegmentMetrics(
        segment=segment,
        samples=len(values),
        avg_return_30d_pct=round(sum(returns) / len(returns), 6),
        return_std_30d_pct=round(stddev(returns), 6),
        avg_drawdown_30d_pct=round(sum(drawdowns) / len(drawdowns), 6),
        worst_drawdown_30d_pct=round(min(drawdowns), 6),
        directional_accuracy=round(directional_hits / len(returns), 6),
    )


def max_drawdown_from_returns(returns_pct: list[float]) -> float:
    if not returns_pct:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1.0 + (r / 100.0))
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = ((equity - peak) / peak) * 100.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


def aggregate_backtest_segment(
    segment: str,
    returns_pct: list[float],
    horizon_days: int,
) -> schemas.BacktestV2Segment:
    if not returns_pct:
        return schemas.BacktestV2Segment(segment=segment, samples=0)
    samples = len(returns_pct)
    avg_return = sum(returns_pct) / samples
    return_std = stddev(returns_pct)
    hit_rate = sum(1 for r in returns_pct if r > 0) / samples
    if return_std > 0:
        sharpe = (avg_return / return_std) * math.sqrt(365.0 / float(horizon_days))
    else:
        sharpe = 0.0
    max_dd = max_drawdown_from_returns(returns_pct)
    return schemas.BacktestV2Segment(
        segment=segment,
        samples=samples,
        avg_return_pct=round(avg_return, 6),
        return_std_pct=round(return_std, 6),
        hit_rate=round(hit_rate, 6),
        sharpe=round(sharpe, 6),
        max_drawdown_pct=round(max_dd, 6),
    )


def policy_zone(score: float, lower_threshold: float, upper_threshold: float) -> str:
    if score <= lower_threshold:
        return "risk_off"
    if score >= upper_threshold:
        return "risk_on"
    return "neutral"


def format_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def to_year_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def compute_walk_forward_month_metrics(
    rows: list[tuple[date, float, float]],
    lower_threshold: float,
    upper_threshold: float,
    horizon_days: int,
) -> tuple[int, int, float | None, float | None, float | None, float | None, float | None]:
    if not rows:
        return 0, 0, None, None, None, None, None

    future_returns = [x[2] for x in rows]
    strategy_returns: list[float] = []
    active_signals = 0
    hit_count = 0
    for _, score, future_return in rows:
        if score >= upper_threshold:
            strategy_returns.append(future_return)
            active_signals += 1
            if future_return > 0:
                hit_count += 1
        elif score <= lower_threshold:
            strategy_returns.append(-future_return)
            active_signals += 1
            if future_return < 0:
                hit_count += 1
        else:
            strategy_returns.append(0.0)

    avg_future_return = sum(future_returns) / len(future_returns) if future_returns else None
    avg_strategy_return = sum(strategy_returns) / len(strategy_returns) if strategy_returns else None
    hit_rate = (hit_count / active_signals) if active_signals > 0 else None
    std_strategy = stddev(strategy_returns)
    sharpe = ((avg_strategy_return / std_strategy) * math.sqrt(365.0 / float(horizon_days))) if std_strategy > 0 else None
    max_dd = max_drawdown_from_returns(strategy_returns)
    return (
        len(rows),
        active_signals,
        avg_future_return,
        avg_strategy_return,
        hit_rate,
        sharpe,
        max_dd,
    )
