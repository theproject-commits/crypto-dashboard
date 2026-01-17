import time
import sys
from datetime import datetime, timedelta
from pathlib import Path
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

load_dotenv()

# Instantiate the CoinGecko API client
cg = CoinGeckoAPI()

# CoinGecko free API has a rate limit of ~50 calls/minute.
# We will add a sleep to respect this limit.
REQUEST_DELAY_SECONDS = 1.5 # ~40 requests per minute, staying safely below the limit.

def populate_cryptocurrencies(db: Session):
    print("Populating cryptocurrencies...")
    try:
        markets_data = cg.get_coins_markets(
            vs_currency="usd",
            order="market_cap_desc",
            per_page=250, # Fetch top 250 coins
            page=1,
            sparkline=False
        )
    except Exception as e:
        print(f"Error fetching markets data from CoinGecko API: {e}")
        markets_data = None

    if not markets_data:
        print("Failed to fetch markets data. Exiting.")
        return

    for crypto_data in markets_data:
        coingecko_id = crypto_data["id"]
        db_crypto = get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)

        if not db_crypto:
            crypto_schema = CryptocurrencyCreate(
                coingecko_id=coingecko_id,
                symbol=crypto_data["symbol"].lower(),
                name=crypto_data["name"],
                image_url=crypto_data["image"]
            )
            create_cryptocurrency(db=db, crypto=crypto_schema)
            print(f"Added {crypto_data['name']} to database.")
        else:
            # Optionally update existing crypto details if needed
            print(f"{crypto_data['name']} already exists. Skipping.")
    print("Cryptocurrencies population complete.")

def populate_price_history(db: Session, days: int = 365):
    print(f"Populating price history for the last {days} days...")
    cryptos = get_cryptocurrencies(db)
    
    for crypto in cryptos:
        print(f"Fetching history for {crypto.name} ({crypto.coingecko_id})...")
        try:
            # The SDK handles the timestamp conversion
            end_timestamp = datetime.now()
            start_timestamp = end_timestamp - timedelta(days=days)

            market_chart_data = cg.get_coin_market_chart_range_by_id(
                id=crypto.coingecko_id,
                vs_currency="usd",
                from_timestamp=str(start_timestamp.timestamp()),
                to_timestamp=str(end_timestamp.timestamp())
            )
        except Exception as e:
            print(f"Error fetching market chart data for {crypto.name}: {e}")
            market_chart_data = None
        
        # Always sleep to respect the rate limit, even on failure, to avoid hammering the API
        time.sleep(REQUEST_DELAY_SECONDS)

        if not market_chart_data:
            print(f"Failed to fetch market chart data for {crypto.name}. Skipping.")
            continue

        prices = market_chart_data.get("prices", [])
        market_caps = market_chart_data.get("market_caps", [])
        total_volumes = market_chart_data.get("total_volumes", [])

        # Assuming prices, market_caps, total_volumes are aligned by timestamp
        for i in range(len(prices)):
            timestamp_ms = prices[i][0]
            entry_date = datetime.fromtimestamp(timestamp_ms / 1000).date()

            # Check if this entry already exists for the specific date
            existing_entry = get_price_history_by_crypto_id_and_date(db, crypto_id=crypto.id, date=entry_date)
            if existing_entry:
                continue

            try:
                price_data_schema = PriceHistoryCreate(
                    date=entry_date,
                    price_usd=prices[i][1],
                    market_cap_usd=int(market_caps[i][1]),
                    total_volume_usd=int(total_volumes[i][1])
                )
                create_price_history_entry(db=db, price_data=price_data_schema, crypto_id=crypto.id)
            except Exception as e:
                print(f"Error adding price history for {crypto.name} on {entry_date}: {e}")
        
        print(f"Finished fetching history for {crypto.name}.")

    print("Price history population complete.")

def create_tables():
    print("Creating database tables...")
    from models import Base
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

if __name__ == "__main__":
    db = SessionLocal()
    try:
        create_tables()
        populate_cryptocurrencies(db)
        populate_price_history(db, days=365)
    finally:
        db.close()
