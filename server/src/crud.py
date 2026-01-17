from sqlalchemy.orm import Session
from . import models, schemas
from datetime import date

def get_cryptocurrency_by_coingecko_id(db: Session, coingecko_id: str):
    return db.query(models.Cryptocurrency).filter(models.Cryptocurrency.coingecko_id == coingecko_id).first()

def create_cryptocurrency(db: Session, crypto: schemas.CryptocurrencyCreate):
    db_crypto = models.Cryptocurrency(
        coingecko_id=crypto.coingecko_id,
        symbol=crypto.symbol,
        name=crypto.name,
        image_url=crypto.image_url
    )
    db.add(db_crypto)
    db.commit()
    db.refresh(db_crypto)
    return db_crypto

def get_cryptocurrencies(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Cryptocurrency).offset(skip).limit(limit).all()

def create_price_history_entry(db: Session, price_data: schemas.PriceHistoryCreate, crypto_id: int):
    db_price_history = models.PriceHistory(
        crypto_id=crypto_id,
        date=price_data.date,
        price_usd=price_data.price_usd,
        market_cap_usd=price_data.market_cap_usd,
        total_volume_usd=price_data.total_volume_usd
    )
    db.add(db_price_history)
    db.commit()
    db.refresh(db_price_history)
    return db_price_history

def get_price_history(db: Session, crypto_id: int, start_date: date, end_date: date):
    return db.query(models.PriceHistory).filter(
        models.PriceHistory.crypto_id == crypto_id,
        models.PriceHistory.date >= start_date,
        models.PriceHistory.date <= end_date
    ).order_by(models.PriceHistory.date).all()

def get_price_history_by_crypto_id_and_date(db: Session, crypto_id: int, date: date):
    return db.query(models.PriceHistory).filter(
        models.PriceHistory.crypto_id == crypto_id,
        models.PriceHistory.date == date
    ).first()
