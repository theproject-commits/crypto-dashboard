from sqlalchemy import Column, Integer, String, Date, DECIMAL, ForeignKey, BigInteger, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

try:
    from .database import Base
except ImportError:
    from database import Base

class Cryptocurrency(Base):
    __tablename__ = "cryptocurrencies"

    id = Column(Integer, primary_key=True, index=True)
    coingecko_id = Column(String, unique=True, index=True, nullable=False)
    symbol = Column(String, index=True, nullable=False)
    name = Column(String, index=True, nullable=False)
    image_url = Column(String, nullable=True)
    last_updated = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())

    price_history = relationship("PriceHistory", back_populates="cryptocurrency")

class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    crypto_id = Column(Integer, ForeignKey("cryptocurrencies.id"), nullable=False)
    date = Column(Date, index=True, nullable=False)
    price_usd = Column(DECIMAL(20, 10), nullable=False)
    market_cap_usd = Column(BigInteger, nullable=False)
    total_volume_usd = Column(BigInteger, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())

    cryptocurrency = relationship("Cryptocurrency", back_populates="price_history")
