from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional

class CryptocurrencyBase(BaseModel):
    coingecko_id: str
    symbol: str
    name: str
    image_url: Optional[str] = None

class CryptocurrencyCreate(CryptocurrencyBase):
    pass

class Cryptocurrency(CryptocurrencyBase):
    id: int
    last_updated: datetime

    class Config:
        from_attributes = True

class PriceHistoryBase(BaseModel):
    date: date
    price_usd: float
    market_cap_usd: int
    total_volume_usd: int

class PriceHistoryCreate(PriceHistoryBase):
    pass

class PriceHistory(PriceHistoryBase):
    id: int
    crypto_id: int
    created_at: datetime

    class Config:
        from_attributes = True
