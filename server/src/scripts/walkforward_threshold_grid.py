from __future__ import annotations

import argparse
import json
import math
from datetime import date

from .. import crud
from ..database import SessionLocal


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _max_drawdown_from_returns(returns_pct: list[float]) -> float:
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


def _to_year_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _future_returns_by_snapshot_date(
    price_by_date: dict[date, float],
    horizon_days: int,
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


def _strategy_metrics(
    rows: list[tuple[date, float, float]],
    lower_threshold: float,
    upper_threshold: float,
    horizon_days: int,
) -> dict:
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

    if not strategy_returns:
        return {
            "samples": 0,
            "active_signals": 0,
            "active_ratio": 0.0,
            "avg_strategy_return_pct": None,
            "hit_rate": None,
            "sharpe": None,
            "max_drawdown_pct": None,
        }

    avg_strategy = sum(strategy_returns) / len(strategy_returns)
    hit_rate = (hit_count / active_signals) if active_signals > 0 else None
    strategy_std = _stddev(strategy_returns)
    sharpe = ((avg_strategy / strategy_std) * math.sqrt(365.0 / float(horizon_days))) if strategy_std > 0 else None
    return {
        "samples": len(strategy_returns),
        "active_signals": active_signals,
        "active_ratio": active_signals / len(strategy_returns),
        "avg_strategy_return_pct": avg_strategy,
        "hit_rate": hit_rate,
        "sharpe": sharpe,
        "max_drawdown_pct": _max_drawdown_from_returns(strategy_returns),
    }


def _evaluate_candidate_on_train(
    rows: list[tuple[date, float, float]],
    lower: float,
    upper: float,
    horizon_days: int,
    prev_choice: tuple[float, float] | None,
    stability_penalty: float,
) -> tuple[float, dict]:
    metrics = _strategy_metrics(rows, lower_threshold=lower, upper_threshold=upper, horizon_days=horizon_days)
    if metrics["samples"] == 0:
        return -10_000.0, metrics
    active_ratio = float(metrics["active_ratio"])
    sharpe = float(metrics["sharpe"] or 0.0)
    avg = float(metrics["avg_strategy_return_pct"] or 0.0)

    # Penalize extremes in signal frequency to reduce brittle thresholds.
    coverage_penalty = 0.0
    if active_ratio < 0.03:
        coverage_penalty += (0.03 - active_ratio) * 6.0
    if active_ratio > 0.35:
        coverage_penalty += (active_ratio - 0.35) * 4.0

    stability_cost = 0.0
    if prev_choice is not None:
        prev_l, prev_u = prev_choice
        stability_cost = (abs(lower - prev_l) + abs(upper - prev_u)) / 100.0

    objective = (0.70 * sharpe) + (0.30 * avg / 10.0) - coverage_penalty - (stability_penalty * stability_cost)
    return objective, metrics


def _grid_pairs(lowers: list[float], uppers: list[float]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for lower in lowers:
        for upper in uppers:
            if lower < upper:
                out.append((lower, upper))
    return out


def _parse_float_list(raw: str) -> list[float]:
    vals = []
    for x in raw.split(","):
        x = x.strip()
        if not x:
            continue
        vals.append(float(x))
    return vals


def _parse_int_list(raw: str) -> list[int]:
    vals = []
    for x in raw.split(","):
        x = x.strip()
        if not x:
            continue
        vals.append(int(x))
    return vals


def _parse_str_list(raw: str) -> list[str]:
    vals = []
    for x in raw.split(","):
        x = x.strip().lower()
        if not x:
            continue
        vals.append(x)
    return list(dict.fromkeys(vals))


def _build_aligned_rows(db, coingecko_id: str, horizon_days: int, limit: int) -> list[tuple[date, float, float]]:
    crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if crypto is None:
        return []
    history = crud.get_price_history_all(db, crypto_id=crypto.id)
    price_by_date = {entry.date: float(entry.price_usd) for entry in history}
    future_returns = _future_returns_by_snapshot_date(price_by_date=price_by_date, horizon_days=horizon_days)
    snapshots = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=crypto.id,
        horizon_days=horizon_days,
        limit=limit,
    )
    rows: list[tuple[date, float, float]] = []
    for row in reversed(snapshots):
        fwd = future_returns.get(row.snapshot_date)
        if fwd is None:
            continue
        rows.append((row.snapshot_date, float(row.composite_score), float(fwd)))
    return rows


def run_walkforward_threshold_grid(
    db,
    coingecko_id: str,
    horizon_days: int,
    min_train_months: int,
    lowers: list[float],
    uppers: list[float],
    stability_penalty: float,
    limit: int,
) -> dict:
    rows = _build_aligned_rows(db=db, coingecko_id=coingecko_id, horizon_days=horizon_days, limit=limit)
    if len(rows) < 120:
        return {"coingecko_id": coingecko_id, "horizon_days": horizon_days, "error": "insufficient_rows"}

    rows_by_month: dict[str, list[tuple[date, float, float]]] = {}
    for row in rows:
        rows_by_month.setdefault(_to_year_month(row[0]), []).append(row)
    months = sorted(rows_by_month.keys())
    if len(months) <= min_train_months:
        return {"coingecko_id": coingecko_id, "horizon_days": horizon_days, "error": "insufficient_months"}

    pairs = _grid_pairs(lowers=lowers, uppers=uppers)
    if not pairs:
        return {"coingecko_id": coingecko_id, "horizon_days": horizon_days, "error": "empty_grid"}

    prev_choice: tuple[float, float] | None = None
    month_results: list[dict] = []
    aggregate_returns: list[float] = []
    aggregate_active = 0
    aggregate_hits = 0

    for idx in range(min_train_months, len(months)):
        train_months = months[:idx]
        test_month = months[idx]
        train_rows = [row for m in train_months for row in rows_by_month[m]]
        test_rows = rows_by_month[test_month]
        if not train_rows or not test_rows:
            continue

        best_objective = -10_000.0
        best_choice = pairs[0]
        for lower, upper in pairs:
            objective, _ = _evaluate_candidate_on_train(
                rows=train_rows,
                lower=lower,
                upper=upper,
                horizon_days=horizon_days,
                prev_choice=prev_choice,
                stability_penalty=stability_penalty,
            )
            if objective > best_objective:
                best_objective = objective
                best_choice = (lower, upper)

        lower_star, upper_star = best_choice
        prev_choice = best_choice
        test_metrics = _strategy_metrics(
            rows=test_rows,
            lower_threshold=lower_star,
            upper_threshold=upper_star,
            horizon_days=horizon_days,
        )
        ge70 = [ret for _, score, ret in test_rows if score >= 70.0]
        lt30 = [ret for _, score, ret in test_rows if score < 30.0]
        ge70_avg = (sum(ge70) / len(ge70)) if ge70 else None
        lt30_avg = (sum(lt30) / len(lt30)) if lt30 else None

        month_results.append(
            {
                "month": test_month,
                "lower_threshold": lower_star,
                "upper_threshold": upper_star,
                "train_samples": len(train_rows),
                "test_samples": test_metrics["samples"],
                "active_signals": test_metrics["active_signals"],
                "active_ratio": test_metrics["active_ratio"],
                "avg_strategy_return_pct": test_metrics["avg_strategy_return_pct"],
                "hit_rate": test_metrics["hit_rate"],
                "sharpe": test_metrics["sharpe"],
                "max_drawdown_pct": test_metrics["max_drawdown_pct"],
                "bucket_ge70_avg_return_pct": ge70_avg,
                "bucket_lt30_avg_return_pct": lt30_avg,
            }
        )

        # rebuild signal sequence for aggregate
        for _, score, ret in test_rows:
            if score >= upper_star:
                aggregate_returns.append(ret)
                aggregate_active += 1
                if ret > 0:
                    aggregate_hits += 1
            elif score <= lower_star:
                aggregate_returns.append(-ret)
                aggregate_active += 1
                if ret < 0:
                    aggregate_hits += 1
            else:
                aggregate_returns.append(0.0)

    if not month_results:
        return {"coingecko_id": coingecko_id, "horizon_days": horizon_days, "error": "no_month_results"}

    avg_strategy = sum(aggregate_returns) / len(aggregate_returns) if aggregate_returns else None
    std_strategy = _stddev(aggregate_returns)
    sharpe = ((avg_strategy / std_strategy) * math.sqrt(365.0 / float(horizon_days))) if std_strategy > 0 else None
    hit_rate = (aggregate_hits / aggregate_active) if aggregate_active > 0 else None

    ge70_vals = [x["bucket_ge70_avg_return_pct"] for x in month_results if x["bucket_ge70_avg_return_pct"] is not None]
    lt30_vals = [x["bucket_lt30_avg_return_pct"] for x in month_results if x["bucket_lt30_avg_return_pct"] is not None]
    ge70_avg = (sum(ge70_vals) / len(ge70_vals)) if ge70_vals else None
    lt30_avg = (sum(lt30_vals) / len(lt30_vals)) if lt30_vals else None
    spread = (ge70_avg - lt30_avg) if ge70_avg is not None and lt30_avg is not None else None

    return {
        "coingecko_id": coingecko_id,
        "horizon_days": horizon_days,
        "min_train_months": min_train_months,
        "stability_penalty": stability_penalty,
        "lowers": lowers,
        "uppers": uppers,
        "months": month_results,
        "summary": {
            "test_samples": len(aggregate_returns),
            "active_signals": aggregate_active,
            "active_ratio": (aggregate_active / len(aggregate_returns)) if aggregate_returns else 0.0,
            "hit_rate": hit_rate,
            "avg_strategy_return_pct": avg_strategy,
            "sharpe": sharpe,
            "max_drawdown_pct": _max_drawdown_from_returns(aggregate_returns),
            "bucket_ge70_avg_return_pct": ge70_avg,
            "bucket_lt30_avg_return_pct": lt30_avg,
            "bucket_spread_pct": spread,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward threshold grid for composite v2.")
    parser.add_argument("--coins", default="bitcoin,ethereum")
    parser.add_argument("--horizons", default="7,14,30")
    parser.add_argument("--min-train-months", type=int, default=12)
    parser.add_argument("--lowers", default="20,25,30,35,40")
    parser.add_argument("--uppers", default="60,65,70,75,80")
    parser.add_argument("--stability-penalty", type=float, default=0.20)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    coins = _parse_str_list(args.coins)
    horizons = _parse_int_list(args.horizons)
    lowers = _parse_float_list(args.lowers)
    uppers = _parse_float_list(args.uppers)

    db = SessionLocal()
    try:
        reports = []
        for coin in coins:
            for horizon in horizons:
                report = run_walkforward_threshold_grid(
                    db=db,
                    coingecko_id=coin,
                    horizon_days=horizon,
                    min_train_months=args.min_train_months,
                    lowers=lowers,
                    uppers=uppers,
                    stability_penalty=args.stability_penalty,
                    limit=args.limit,
                )
                reports.append(report)
                summary = report.get("summary")
                if summary is None:
                    print(f"{coin} {horizon}d | error={report.get('error')}")
                    continue
                print(
                    f"{coin} {horizon}d | active={summary['active_signals']}/{summary['test_samples']} "
                    f"({summary['active_ratio']*100:.2f}%) hit={summary['hit_rate']:.4f} "
                    f"sharpe={summary['sharpe']:.4f} spread={summary['bucket_spread_pct']:.4f}"
                )
        if args.json:
            print(json.dumps(reports, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
