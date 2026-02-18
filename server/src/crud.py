from sqlalchemy.orm import Session, joinedload
from datetime import date, datetime
from pycoingecko import CoinGeckoAPI

try:
    from . import models, schemas
except ImportError:
    import models
    import schemas

cg = CoinGeckoAPI()

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
    return db.query(models.Cryptocurrency).options(joinedload(models.Cryptocurrency.price_history)).offset(skip).limit(limit).all()

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

def get_price_history_all(db: Session, crypto_id: int):
    return db.query(models.PriceHistory).filter(
        models.PriceHistory.crypto_id == crypto_id
    ).order_by(models.PriceHistory.date).all()

def get_price_history_by_crypto_id_and_date(db: Session, crypto_id: int, date: date):
    return db.query(models.PriceHistory).filter(
        models.PriceHistory.crypto_id == crypto_id,
        models.PriceHistory.date == date
    ).first()


def get_market_state_snapshot_by_crypto_and_date(db: Session, crypto_id: int, snapshot_date: date):
    return db.query(models.MarketStateSnapshot).filter(
        models.MarketStateSnapshot.crypto_id == crypto_id,
        models.MarketStateSnapshot.snapshot_date == snapshot_date,
    ).first()


def upsert_market_state_snapshot(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
    state: schemas.MarketStateResponse,
):
    row = get_market_state_snapshot_by_crypto_and_date(db, crypto_id=crypto_id, snapshot_date=snapshot_date)
    payload = {
        "regime": state.regime,
        "probability_up": float(state.probability_up),
        "probability_flat": float(state.probability_flat),
        "probability_down": float(state.probability_down),
        "risk_score": float(state.risk_score),
        "asymmetry_score": float(state.asymmetry_score),
        "momentum_structural_score": float(state.momentum_structural_score),
        "volatility_future_7d_pct": float(state.volatility_future_7d_pct),
        "volatility_future_30d_pct": float(state.volatility_future_30d_pct),
        "confidence": float(state.confidence),
        "last_price_usd": float(state.last_price_usd),
        "momentum_30d_pct": float(state.components.momentum_30d_pct),
        "momentum_90d_pct": float(state.components.momentum_90d_pct),
        "sma20_sma50_spread_pct": float(state.components.sma20_sma50_spread_pct),
        "rsi_14": float(state.components.rsi_14),
        "volatility_30d_pct": float(state.components.volatility_30d_pct),
        "drawdown_180d_pct": float(state.components.drawdown_180d_pct),
        "volume_zscore_30": float(state.components.volume_zscore_30),
        "generated_at": state.generated_at,
    }
    if row is None:
        row = models.MarketStateSnapshot(
            crypto_id=crypto_id,
            snapshot_date=snapshot_date,
            **payload,
        )
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def get_market_state_history(
    db: Session,
    crypto_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 365,
):
    query = db.query(models.MarketStateSnapshot).filter(models.MarketStateSnapshot.crypto_id == crypto_id)
    if start_date is not None:
        query = query.filter(models.MarketStateSnapshot.snapshot_date >= start_date)
    if end_date is not None:
        query = query.filter(models.MarketStateSnapshot.snapshot_date <= end_date)
    return query.order_by(models.MarketStateSnapshot.snapshot_date.desc()).limit(limit).all()


def get_market_state_performance_snapshot_by_crypto_and_date(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
    horizon_days: int = 30,
):
    return db.query(models.MarketStatePerformanceSnapshot).filter(
        models.MarketStatePerformanceSnapshot.crypto_id == crypto_id,
        models.MarketStatePerformanceSnapshot.snapshot_date == snapshot_date,
        models.MarketStatePerformanceSnapshot.horizon_days == horizon_days,
    ).first()


def upsert_market_state_performance_snapshot(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
    horizon_days: int,
    samples: int,
    directional_accuracy: float,
    brier_score: float,
    avg_future_return_pct: float | None,
    avg_probability_up: float,
    generated_at: datetime,
):
    row = get_market_state_performance_snapshot_by_crypto_and_date(
        db,
        crypto_id=crypto_id,
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
    )
    payload = {
        "samples": int(samples),
        "directional_accuracy": float(directional_accuracy),
        "brier_score": float(brier_score),
        "avg_future_return_pct": float(avg_future_return_pct) if avg_future_return_pct is not None else None,
        "avg_probability_up": float(avg_probability_up),
        "generated_at": generated_at,
    }
    if row is None:
        row = models.MarketStatePerformanceSnapshot(
            crypto_id=crypto_id,
            snapshot_date=snapshot_date,
            horizon_days=horizon_days,
            **payload,
        )
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def get_market_state_performance_history(
    db: Session,
    crypto_id: int,
    horizon_days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 365,
):
    query = db.query(models.MarketStatePerformanceSnapshot).filter(
        models.MarketStatePerformanceSnapshot.crypto_id == crypto_id,
        models.MarketStatePerformanceSnapshot.horizon_days == horizon_days,
    )
    if start_date is not None:
        query = query.filter(models.MarketStatePerformanceSnapshot.snapshot_date >= start_date)
    if end_date is not None:
        query = query.filter(models.MarketStatePerformanceSnapshot.snapshot_date <= end_date)
    return query.order_by(models.MarketStatePerformanceSnapshot.snapshot_date.desc()).limit(limit).all()


def get_market_composite_snapshot_by_crypto_and_date(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
):
    return db.query(models.MarketCompositeSnapshot).filter(
        models.MarketCompositeSnapshot.crypto_id == crypto_id,
        models.MarketCompositeSnapshot.snapshot_date == snapshot_date,
    ).first()


def upsert_market_composite_snapshot(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
    horizon_days: int,
    regime_score: float,
    flow_score: float,
    sentiment_score: float,
    composite_score: float,
    label: str,
    confidence: float,
    generated_at: datetime,
):
    row = get_market_composite_snapshot_by_crypto_and_date(
        db=db,
        crypto_id=crypto_id,
        snapshot_date=snapshot_date,
    )
    payload = {
        "horizon_days": int(horizon_days),
        "regime_score": float(regime_score),
        "flow_score": float(flow_score),
        "sentiment_score": float(sentiment_score),
        "composite_score": float(composite_score),
        "label": str(label),
        "confidence": float(confidence),
        "generated_at": generated_at,
    }
    if row is None:
        row = models.MarketCompositeSnapshot(
            crypto_id=crypto_id,
            snapshot_date=snapshot_date,
            **payload,
        )
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def get_market_composite_history(
    db: Session,
    crypto_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 365,
):
    query = db.query(models.MarketCompositeSnapshot).filter(
        models.MarketCompositeSnapshot.crypto_id == crypto_id
    )
    if start_date is not None:
        query = query.filter(models.MarketCompositeSnapshot.snapshot_date >= start_date)
    if end_date is not None:
        query = query.filter(models.MarketCompositeSnapshot.snapshot_date <= end_date)
    return query.order_by(models.MarketCompositeSnapshot.snapshot_date.desc()).limit(limit).all()


def get_market_composite_v2_snapshot_by_crypto_date_and_horizon(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
    horizon_days: int = 30,
):
    return db.query(models.MarketCompositeV2Snapshot).filter(
        models.MarketCompositeV2Snapshot.crypto_id == crypto_id,
        models.MarketCompositeV2Snapshot.snapshot_date == snapshot_date,
        models.MarketCompositeV2Snapshot.horizon_days == horizon_days,
    ).first()


def upsert_market_composite_v2_snapshot(
    db: Session,
    crypto_id: int,
    snapshot_date: date,
    horizon_days: int,
    regime_score: float,
    flow_score: float,
    sentiment_score: float | None,
    risk_score: float,
    regime_weight: float,
    flow_weight: float,
    sentiment_weight: float,
    risk_weight: float,
    composite_score: float,
    label: str,
    confidence: float,
    generated_at: datetime,
):
    row = get_market_composite_v2_snapshot_by_crypto_date_and_horizon(
        db=db,
        crypto_id=crypto_id,
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
    )
    payload = {
        "horizon_days": int(horizon_days),
        "regime_score": float(regime_score),
        "flow_score": float(flow_score),
        "sentiment_score": float(sentiment_score) if sentiment_score is not None else None,
        "risk_score": float(risk_score),
        "regime_weight": float(regime_weight),
        "flow_weight": float(flow_weight),
        "sentiment_weight": float(sentiment_weight),
        "risk_weight": float(risk_weight),
        "composite_score": float(composite_score),
        "label": str(label),
        "confidence": float(confidence),
        "generated_at": generated_at,
    }
    if row is None:
        row = models.MarketCompositeV2Snapshot(
            crypto_id=crypto_id,
            snapshot_date=snapshot_date,
            **payload,
        )
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def get_market_composite_v2_history(
    db: Session,
    crypto_id: int,
    horizon_days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 365,
):
    query = db.query(models.MarketCompositeV2Snapshot).filter(
        models.MarketCompositeV2Snapshot.crypto_id == crypto_id,
        models.MarketCompositeV2Snapshot.horizon_days == horizon_days,
    )
    if start_date is not None:
        query = query.filter(models.MarketCompositeV2Snapshot.snapshot_date >= start_date)
    if end_date is not None:
        query = query.filter(models.MarketCompositeV2Snapshot.snapshot_date <= end_date)
    return query.order_by(models.MarketCompositeV2Snapshot.snapshot_date.desc()).limit(limit).all()

def populate_price_history_from_coingecko(db: Session, coingecko_id: str, days: int = 30):
    """
    Fetches historical price data from CoinGecko and populates the database.
    """
    db_crypto = get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if not db_crypto:
        return None

    try:
        market_chart = cg.get_coin_market_chart_by_id(id=coingecko_id, vs_currency='usd', days=days)
    except Exception:
        return False

    if (
        not market_chart
        or 'prices' not in market_chart
        or 'market_caps' not in market_chart
        or 'total_volumes' not in market_chart
    ):
        return False

    for i in range(len(market_chart['prices'])):
        try:
            timestamp = market_chart['prices'][i][0] / 1000  # Convert ms to s
            entry_date = datetime.fromtimestamp(timestamp).date()

            # Check if entry for this date already exists
            existing_entry = get_price_history_by_crypto_id_and_date(db, db_crypto.id, entry_date)
            if existing_entry:
                continue

            price_data = schemas.PriceHistoryCreate(
                date=entry_date,
                price_usd=market_chart['prices'][i][1],
                market_cap_usd=market_chart['market_caps'][i][1],
                total_volume_usd=market_chart['total_volumes'][i][1]
            )
            create_price_history_entry(db, price_data, db_crypto.id)
        except (IndexError, TypeError, ValueError):
            continue
    return True

