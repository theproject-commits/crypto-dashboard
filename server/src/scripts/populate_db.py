import time
import sys
import json
import logging
import argparse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Union
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from pycoingecko import CoinGeckoAPI

# Add parent directories to path to allow imports when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal, engine
from models import Cryptocurrency, PriceHistory
from schemas import CryptocurrencyCreate, PriceHistoryCreate
from crud import (
    create_cryptocurrency,
    create_price_history_entry,
    get_cryptocurrency_by_coingecko_id,
    get_cryptocurrencies,
    get_price_history_by_crypto_id_and_date
)
from providers.binance import fetch_daily_history

load_dotenv()

# Instantiate the CoinGecko API client
cg = CoinGeckoAPI()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("populate_db")

# CoinGecko free API has a rate limit of ~50 calls/minute.
# We will add a sleep to respect this limit.
REQUEST_DELAY_SECONDS = 1.5 # ~40 requests per minute, staying safely below the limit.
BINANCE_SYMBOLS = {
    "bitcoin": {"symbol": "BTCUSDT", "start_date": date(2017, 8, 17)},
    "ethereum": {"symbol": "ETHUSDT", "start_date": date(2017, 8, 17)},
}
DEFAULT_CRYPTOS = {
    "bitcoin": {"symbol": "btc", "name": "Bitcoin"},
    "ethereum": {"symbol": "eth", "name": "Ethereum"},
}
SUPPORTED_COINS = sorted(DEFAULT_CRYPTOS.keys())


HistoryWindow = Union[int, str]


def log_event(level: int, event: str, **fields):
    payload = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        **fields,
    }
    logger.log(level, json.dumps(payload, default=str, sort_keys=True))

def parse_coin_list(raw_coins: str):
    coins = [coin.strip().lower() for coin in raw_coins.split(",") if coin.strip()]
    if not coins:
        return []
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(coins))


def populate_cryptocurrencies(db: Session, target_coins=None):
    if target_coins is None:
        target_coins = SUPPORTED_COINS
    log_event(logging.INFO, "populate_cryptocurrencies.start", target_coins=target_coins)

    for coingecko_id in target_coins:
        db_crypto = get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)

        if not db_crypto:
            try:
                # Fetch specific coin data to get details
                crypto_data = cg.get_coin_by_id(id=coingecko_id)
                time.sleep(REQUEST_DELAY_SECONDS) # Respect rate limit
                
                if not crypto_data:
                    log_event(logging.WARNING, "populate_cryptocurrencies.fetch_empty", coingecko_id=coingecko_id)
                    continue

                crypto_schema = CryptocurrencyCreate(
                    coingecko_id=coingecko_id,
                    symbol=crypto_data["symbol"].lower(),
                    name=crypto_data["name"],
                    image_url=crypto_data["image"]["large"]
                )
                create_cryptocurrency(db=db, crypto=crypto_schema)
                log_event(
                    logging.INFO,
                    "populate_cryptocurrencies.created",
                    coingecko_id=coingecko_id,
                    name=crypto_data["name"],
                )

            except Exception as e:
                fallback = DEFAULT_CRYPTOS.get(coingecko_id)
                if fallback:
                    crypto_schema = CryptocurrencyCreate(
                        coingecko_id=coingecko_id,
                        symbol=fallback["symbol"],
                        name=fallback["name"],
                        image_url=None,
                    )
                    create_cryptocurrency(db=db, crypto=crypto_schema)
                    log_event(
                        logging.WARNING,
                        "populate_cryptocurrencies.created_fallback",
                        coingecko_id=coingecko_id,
                        error=str(e),
                    )
                else:
                    log_event(
                        logging.ERROR,
                        "populate_cryptocurrencies.fetch_error",
                        coingecko_id=coingecko_id,
                        error=str(e),
                    )
        else:
            log_event(
                logging.INFO,
                "populate_cryptocurrencies.exists",
                coingecko_id=coingecko_id,
                name=db_crypto.name,
            )
    log_event(logging.INFO, "populate_cryptocurrencies.complete")

def parse_history_window(raw_days: str) -> HistoryWindow:
    value = raw_days.strip().lower()
    if value == "max":
        return "max"
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--days must be an integer or 'max'.") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--days must be greater than zero or 'max'.")
    return parsed


def populate_price_history(db: Session, days: HistoryWindow = 365, target_coins=None):
    if target_coins is None:
        target_coins = SUPPORTED_COINS
    target_coin_set = set(target_coins)
    log_event(logging.INFO, "populate_price_history.start", days=days, target_coins=target_coins)
    cryptos = get_cryptocurrencies(db)
    
    for crypto in cryptos:
        if crypto.coingecko_id not in target_coin_set:
            continue
        log_event(
            logging.INFO,
            "populate_price_history.fetch_start",
            crypto_id=crypto.id,
            coingecko_id=crypto.coingecko_id,
            name=crypto.name,
        )
        try:
            if days == "max":
                market_chart_data = cg.get_coin_market_chart_by_id(
                    id=crypto.coingecko_id,
                    vs_currency="usd",
                    days="max",
                )
            else:
                # The SDK handles the timestamp conversion.
                end_timestamp = datetime.now()
                start_timestamp = end_timestamp - timedelta(days=days)
                market_chart_data = cg.get_coin_market_chart_range_by_id(
                    id=crypto.coingecko_id,
                    vs_currency="usd",
                    from_timestamp=str(start_timestamp.timestamp()),
                    to_timestamp=str(end_timestamp.timestamp()),
                )
        except Exception as e:
            log_event(
                logging.ERROR,
                "populate_price_history.fetch_error",
                crypto_id=crypto.id,
                coingecko_id=crypto.coingecko_id,
                error=str(e),
            )
            market_chart_data = None
        
        # Always sleep to respect the rate limit, even on failure, to avoid hammering the API
        time.sleep(REQUEST_DELAY_SECONDS)

        if not market_chart_data:
            log_event(
                logging.WARNING,
                "populate_price_history.fetch_empty",
                crypto_id=crypto.id,
                coingecko_id=crypto.coingecko_id,
            )
            continue

        prices = market_chart_data.get("prices", [])
        market_caps = market_chart_data.get("market_caps", [])
        total_volumes = market_chart_data.get("total_volumes", [])
        entry_count = min(len(prices), len(market_caps), len(total_volumes))
        if entry_count == 0:
            log_event(
                logging.WARNING,
                "populate_price_history.no_entries",
                crypto_id=crypto.id,
                coingecko_id=crypto.coingecko_id,
            )
            continue

        # Assuming prices, market_caps, total_volumes are aligned by timestamp
        created_count = 0
        skipped_existing = 0
        skipped_invalid = 0
        for i in range(entry_count):
            timestamp_ms = prices[i][0]
            entry_date = datetime.fromtimestamp(timestamp_ms / 1000).date()

            # Check if this entry already exists for the specific date
            existing_entry = get_price_history_by_crypto_id_and_date(db, crypto_id=crypto.id, date=entry_date)
            if existing_entry:
                skipped_existing += 1
                continue

            try:
                price_data_schema = PriceHistoryCreate(
                    date=entry_date,
                    price_usd=prices[i][1],
                    market_cap_usd=market_caps[i][1],
                    total_volume_usd=total_volumes[i][1]
                )
                create_price_history_entry(db=db, price_data=price_data_schema, crypto_id=crypto.id)
                created_count += 1
            except Exception as e:
                skipped_invalid += 1
                log_event(
                    logging.ERROR,
                    "populate_price_history.insert_error",
                    crypto_id=crypto.id,
                    coingecko_id=crypto.coingecko_id,
                    entry_date=str(entry_date),
                    error=str(e),
                )
        
        log_event(
            logging.INFO,
            "populate_price_history.fetch_complete",
            crypto_id=crypto.id,
            coingecko_id=crypto.coingecko_id,
            entries_requested=len(prices),
            entries_processed=entry_count,
            created_count=created_count,
            skipped_existing=skipped_existing,
            skipped_invalid=skipped_invalid,
        )

    log_event(logging.INFO, "populate_price_history.complete")

def populate_price_history_binance_all_time(db: Session, target_coins=None):
    if target_coins is None:
        target_coins = SUPPORTED_COINS
    targets = [coin for coin in target_coins if coin in BINANCE_SYMBOLS]
    log_event(logging.INFO, "populate_price_history_binance.start", targets=targets)
    for coingecko_id in targets:
        cfg = BINANCE_SYMBOLS[coingecko_id]
        db_crypto = get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
        if not db_crypto:
            log_event(
                logging.ERROR,
                "populate_price_history_binance.missing_crypto",
                coingecko_id=coingecko_id,
            )
            continue

        symbol = cfg["symbol"]
        start_date = cfg["start_date"]
        log_event(
            logging.INFO,
            "populate_price_history_binance.fetch_start",
            coingecko_id=coingecko_id,
            symbol=symbol,
            start_date=str(start_date),
        )
        try:
            rows = fetch_daily_history(symbol=symbol, start_date=start_date)
        except Exception as e:
            log_event(
                logging.ERROR,
                "populate_price_history_binance.fetch_error",
                coingecko_id=coingecko_id,
                symbol=symbol,
                error=str(e),
            )
            continue

        created_count = 0
        skipped_existing = 0
        for row in rows:
            existing_entry = get_price_history_by_crypto_id_and_date(db, crypto_id=db_crypto.id, date=row["date"])
            if existing_entry:
                skipped_existing += 1
                continue

            price_data_schema = PriceHistoryCreate(
                date=row["date"],
                price_usd=row["price_usd"],
                market_cap_usd=0.0,  # Binance klines do not provide market cap.
                total_volume_usd=row["total_volume_usd"],
            )
            create_price_history_entry(db=db, price_data=price_data_schema, crypto_id=db_crypto.id)
            created_count += 1

        log_event(
            logging.INFO,
            "populate_price_history_binance.fetch_complete",
            coingecko_id=coingecko_id,
            symbol=symbol,
            fetched=len(rows),
            created_count=created_count,
            skipped_existing=skipped_existing,
        )

    log_event(logging.INFO, "populate_price_history_binance.complete")

def clear_database(db: Session):
    log_event(logging.INFO, "clear_database.start")
    db.query(PriceHistory).delete()
    db.query(Cryptocurrency).delete()
    db.commit()
    log_event(logging.INFO, "clear_database.complete")

def create_tables():
    log_event(logging.INFO, "create_tables.start")
    from models import Base
    Base.metadata.create_all(bind=engine)
    log_event(logging.INFO, "create_tables.complete")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate crypto database.")
    parser.add_argument(
        "--provider",
        choices=["coingecko", "binance"],
        default="coingecko",
        help="Data provider for price history.",
    )
    parser.add_argument(
        "--days",
        type=parse_history_window,
        default=365,
        help="History window when provider=coingecko. Use an integer (ex: 365) or 'max' for full lifetime.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear tables before population.",
    )
    parser.add_argument(
        "--coins",
        default="bitcoin,ethereum",
        help="Comma-separated coin ids (e.g. bitcoin,ethereum) or 'all' for all coins already stored in DB.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        create_tables()
        if args.clear:
            clear_database(db)
            create_tables()
        coins_arg = args.coins.strip().lower()
        if coins_arg == "all":
            selected_coins = [crypto.coingecko_id for crypto in get_cryptocurrencies(db)]
            if not selected_coins:
                parser.error("No cryptocurrencies found in DB for --coins all.")
        else:
            selected_coins = parse_coin_list(args.coins)
            if not selected_coins:
                parser.error("--coins must contain at least one coin id.")

        populate_cryptocurrencies(db, target_coins=selected_coins)
        if args.provider == "binance":
            populate_price_history_binance_all_time(db, target_coins=selected_coins)
        else:
            populate_price_history(db, days=args.days, target_coins=selected_coins)
    finally:
        db.close()
