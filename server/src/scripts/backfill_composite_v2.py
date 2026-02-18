from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy.orm import Session

from .. import crud
from ..database import SessionLocal
from ..services.composite_v2_engine import compute_composite_v2


def _parse_horizons(raw: str) -> list[int]:
    values = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        values.append(int(piece))
    unique = sorted(set(values))
    return unique or [7, 14, 30]


def _parse_ids(raw: str) -> list[str]:
    values = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return list(dict.fromkeys(values))


def _in_date_range(value: date, start: date | None, end: date | None) -> bool:
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def backfill_for_coin(
    db: Session,
    coingecko_id: str,
    horizons: list[int],
    start_date: date | None,
    end_date: date | None,
) -> tuple[int, int]:
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        return 0, 0

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    if len(history) < 180:
        return 0, 0

    upserted = 0
    skipped = 0
    for idx, row in enumerate(history):
        snapshot_date = row.date
        if not _in_date_range(snapshot_date, start=start_date, end=end_date):
            continue
        if idx < 179:
            skipped += 1
            continue

        sliced = history[: idx + 1]
        prices = [float(x.price_usd) for x in sliced]
        volumes = [float(x.total_volume_usd) for x in sliced]

        try:
            for horizon in horizons:
                payload = compute_composite_v2(
                    coingecko_id=coingecko_id,
                    snapshot_date=snapshot_date,
                    prices=prices,
                    volumes=volumes,
                    horizon_days=horizon,
                    include_external=False,
                )
                crud.upsert_market_composite_v2_snapshot(
                    db=db,
                    crypto_id=db_crypto.id,
                    snapshot_date=snapshot_date,
                    horizon_days=horizon,
                    regime_score=payload["components"]["regime_score"],
                    flow_score=payload["components"]["flow_score"],
                    sentiment_score=payload["components"]["sentiment_score"],
                    risk_score=payload["components"]["risk_score"],
                    regime_weight=payload["components"]["weights"]["regime"],
                    flow_weight=payload["components"]["weights"]["flow"],
                    sentiment_weight=payload["components"]["weights"]["sentiment"],
                    risk_weight=payload["components"]["weights"]["risk"],
                    composite_score=payload["composite_score"],
                    label=payload["label"],
                    confidence=payload["confidence"],
                    generated_at=payload["generated_at"],
                )
                upserted += 1
        except ValueError:
            skipped += 1
            continue

    return upserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical composite v2 snapshots.")
    parser.add_argument("--coins", default="bitcoin,ethereum", help="Comma-separated CoinGecko IDs.")
    parser.add_argument("--horizons", default="7,14,30", help="Comma-separated horizons in days.")
    parser.add_argument("--start-date", default="", help="Optional start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", default="", help="Optional end date (YYYY-MM-DD).")
    args = parser.parse_args()

    coins = _parse_ids(args.coins)
    horizons = _parse_horizons(args.horizons)
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    db = SessionLocal()
    try:
        total_upserted = 0
        total_skipped = 0
        for coingecko_id in coins:
            upserted, skipped = backfill_for_coin(
                db=db,
                coingecko_id=coingecko_id,
                horizons=horizons,
                start_date=start_date,
                end_date=end_date,
            )
            total_upserted += upserted
            total_skipped += skipped
            print(f"[{coingecko_id}] upserted={upserted} skipped={skipped}")
        print(f"[done] total_upserted={total_upserted} total_skipped={total_skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
