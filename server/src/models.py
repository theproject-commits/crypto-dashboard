from sqlalchemy import Column, Integer, String, Date, DECIMAL, ForeignKey, TIMESTAMP, Float, UniqueConstraint
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
    market_state_snapshots = relationship("MarketStateSnapshot", back_populates="cryptocurrency")
    market_state_performance_snapshots = relationship(
        "MarketStatePerformanceSnapshot", back_populates="cryptocurrency"
    )
    market_composite_snapshots = relationship("MarketCompositeSnapshot", back_populates="cryptocurrency")
    market_composite_v2_snapshots = relationship("MarketCompositeV2Snapshot", back_populates="cryptocurrency")

class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    crypto_id = Column(Integer, ForeignKey("cryptocurrencies.id"), nullable=False)
    date = Column(Date, index=True, nullable=False)
    price_usd = Column(DECIMAL(20, 10), nullable=False)
    market_cap_usd = Column(DECIMAL(30, 10), nullable=False)
    total_volume_usd = Column(DECIMAL(30, 10), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())

    cryptocurrency = relationship("Cryptocurrency", back_populates="price_history")


class MarketStateSnapshot(Base):
    __tablename__ = "market_state_snapshots"
    __table_args__ = (
        UniqueConstraint("crypto_id", "snapshot_date", name="uq_market_state_crypto_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    crypto_id = Column(Integer, ForeignKey("cryptocurrencies.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    regime = Column(String, nullable=False)
    probability_up = Column(Float, nullable=False)
    probability_flat = Column(Float, nullable=False)
    probability_down = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    asymmetry_score = Column(Float, nullable=False)
    momentum_structural_score = Column(Float, nullable=False)
    volatility_future_7d_pct = Column(Float, nullable=False)
    volatility_future_30d_pct = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    last_price_usd = Column(Float, nullable=False)
    momentum_30d_pct = Column(Float, nullable=False)
    momentum_90d_pct = Column(Float, nullable=False)
    sma20_sma50_spread_pct = Column(Float, nullable=False)
    rsi_14 = Column(Float, nullable=False)
    volatility_30d_pct = Column(Float, nullable=False)
    drawdown_180d_pct = Column(Float, nullable=False)
    volume_zscore_30 = Column(Float, nullable=False)
    generated_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())

    cryptocurrency = relationship("Cryptocurrency", back_populates="market_state_snapshots")


class MarketStatePerformanceSnapshot(Base):
    __tablename__ = "market_state_performance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "crypto_id",
            "snapshot_date",
            "horizon_days",
            name="uq_market_state_perf_crypto_date_horizon",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    crypto_id = Column(Integer, ForeignKey("cryptocurrencies.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    horizon_days = Column(Integer, nullable=False, default=30)
    samples = Column(Integer, nullable=False)
    directional_accuracy = Column(Float, nullable=False)
    brier_score = Column(Float, nullable=False)
    avg_future_return_pct = Column(Float, nullable=True)
    avg_probability_up = Column(Float, nullable=False)
    generated_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())

    cryptocurrency = relationship("Cryptocurrency", back_populates="market_state_performance_snapshots")


class MarketCompositeSnapshot(Base):
    __tablename__ = "market_composite_snapshots"
    __table_args__ = (
        UniqueConstraint("crypto_id", "snapshot_date", name="uq_market_composite_crypto_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    crypto_id = Column(Integer, ForeignKey("cryptocurrencies.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    horizon_days = Column(Integer, nullable=False, default=30)
    regime_score = Column(Float, nullable=False)
    flow_score = Column(Float, nullable=False)
    sentiment_score = Column(Float, nullable=False)
    composite_score = Column(Float, nullable=False)
    label = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    generated_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())

    cryptocurrency = relationship("Cryptocurrency", back_populates="market_composite_snapshots")


class MarketCompositeV2Snapshot(Base):
    __tablename__ = "market_composite_v2_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "crypto_id",
            "snapshot_date",
            "horizon_days",
            name="uq_market_composite_v2_crypto_date_horizon",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    crypto_id = Column(Integer, ForeignKey("cryptocurrencies.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    horizon_days = Column(Integer, nullable=False, default=30)
    regime_score = Column(Float, nullable=False)
    flow_score = Column(Float, nullable=False)
    sentiment_score = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=False)
    regime_weight = Column(Float, nullable=False)
    flow_weight = Column(Float, nullable=False)
    sentiment_weight = Column(Float, nullable=False)
    risk_weight = Column(Float, nullable=False)
    composite_score = Column(Float, nullable=False)
    label = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    generated_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())

    cryptocurrency = relationship("Cryptocurrency", back_populates="market_composite_v2_snapshots")
