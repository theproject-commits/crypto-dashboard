from pydantic import BaseModel, Field
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
    market_cap_usd: float
    total_volume_usd: float

class PriceHistoryCreate(PriceHistoryBase):
    pass

class PriceHistory(PriceHistoryBase):
    id: int
    crypto_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    message: str


class PredictFeatures(BaseModel):
    momentum_14d_pct: float
    momentum_30d_pct: float
    volatility_30d_pct: float
    rsi_14: float
    sma_20: float
    sma_50: float
    volume_zscore_30: float


class PredictResponse(BaseModel):
    coingecko_id: str
    horizon: str
    signal: str
    probability_up: float
    confidence: float
    generated_at: datetime
    last_price_usd: float
    features: PredictFeatures


class LivePriceResponse(BaseModel):
    coingecko_id: str
    price_usd: float
    fetched_at: datetime
    source: str


class ThemeSettingsUpdateRequest(BaseModel):
    theme: str


class ThemeSettingsResponse(BaseModel):
    theme: str
    source: str


class MarketStateComponents(BaseModel):
    momentum_30d_pct: float
    momentum_90d_pct: float
    sma20_sma50_spread_pct: float
    rsi_14: float
    volatility_30d_pct: float
    drawdown_180d_pct: float
    volume_zscore_30: float


class MarketStateResponse(BaseModel):
    coingecko_id: str
    regime: str
    probability_up: float
    probability_flat: float
    probability_down: float
    risk_score: float
    asymmetry_score: float
    momentum_structural_score: float
    volatility_future_7d_pct: float
    volatility_future_30d_pct: float
    confidence: float
    generated_at: datetime
    last_price_usd: float
    components: MarketStateComponents


class MarketStateSnapshotResponse(BaseModel):
    snapshot_date: date
    regime: str
    probability_up: float
    probability_flat: float
    probability_down: float
    risk_score: float
    asymmetry_score: float
    momentum_structural_score: float
    volatility_future_7d_pct: float
    volatility_future_30d_pct: float
    confidence: float
    last_price_usd: float
    future_return_30d_pct: Optional[float] = None


class MarketStatePerformanceSnapshotResponse(BaseModel):
    snapshot_date: date
    horizon_days: int
    samples: int
    directional_accuracy: float
    brier_score: float
    avg_future_return_pct: Optional[float] = None
    avg_probability_up: float
    generated_at: datetime


class CompositeComponents(BaseModel):
    regime_score: float
    flow_score: float
    sentiment_score: float
    sentiment_source: str


class CompositeResponse(BaseModel):
    coingecko_id: str
    snapshot_date: date
    horizon_days: int
    composite_score: float
    label: str
    confidence: float
    generated_at: datetime
    components: CompositeComponents


class CompositeSnapshotResponse(BaseModel):
    snapshot_date: date
    horizon_days: int
    regime_score: float
    flow_score: float
    sentiment_score: float
    composite_score: float
    label: str
    confidence: float
    generated_at: datetime


class ResearchSegmentMetrics(BaseModel):
    segment: str
    samples: int
    avg_return_30d_pct: Optional[float] = None
    return_std_30d_pct: Optional[float] = None
    avg_drawdown_30d_pct: Optional[float] = None
    worst_drawdown_30d_pct: Optional[float] = None
    directional_accuracy: Optional[float] = None


class CompositeBucketStudyResponse(BaseModel):
    coingecko_id: str
    horizon_days: int
    generated_at: datetime
    segments: list[ResearchSegmentMetrics]


class RegimeConsistencyResponse(BaseModel):
    coingecko_id: str
    horizon_days: int
    generated_at: datetime
    segments: list[ResearchSegmentMetrics]


class ConfidenceCalibrationResponse(BaseModel):
    coingecko_id: str
    horizon_days: int
    generated_at: datetime
    segments: list[ResearchSegmentMetrics]


class CompositeV2Weights(BaseModel):
    regime: float
    flow: float
    sentiment: float
    risk: float


class RegimeV2Components(BaseModel):
    momentum_30d_pct: float
    momentum_90d_pct: float
    sma20_sma50_spread_pct: float
    rsi_14: float
    volatility_30d_pct: float
    drawdown_180d_pct: float
    volume_zscore_30: float
    sma50_slope_pct: float
    price_distance_sma50_pct: float
    atr_compression_ratio: float


class RegimeV2Block(BaseModel):
    score: float
    regime: str
    components: RegimeV2Components


class FlowV2Components(BaseModel):
    symbol: Optional[str] = None
    oi_delta_7d_pct: Optional[float] = None
    funding_avg: Optional[float] = None
    oi_price_divergence: Optional[float] = None
    cvd_proxy_14: float
    price_delta_7d_pct: Optional[float] = None
    volume_zscore_30: float
    volatility_7d_pct: float
    derivatives_available: bool
    derivatives_errors: list[str] = Field(default_factory=list)


class FlowV2Block(BaseModel):
    score: float
    quality: str
    components: FlowV2Components


class SentimentV2Components(BaseModel):
    fear_greed: Optional[float] = None
    trending_rank: Optional[int] = None
    sources_used: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SentimentV2Block(BaseModel):
    score: Optional[float] = None
    quality: str
    components: SentimentV2Components


class RiskV2Components(BaseModel):
    volatility_7d_pct: float
    volatility_30d_pct: float
    atr_expansion_ratio: float
    drawdown_60d_pct: float
    drawdown_180d_pct: float


class RiskV2Block(BaseModel):
    score: float
    risk_state: str
    volatility_event_flag: bool
    components: RiskV2Components


class CompositeV2Components(BaseModel):
    regime_score: float
    flow_score: float
    sentiment_score: Optional[float] = None
    risk_score: float
    weights: CompositeV2Weights
    regime: RegimeV2Block
    flow: FlowV2Block
    sentiment: SentimentV2Block
    risk: RiskV2Block


class CompositeV2Response(BaseModel):
    coingecko_id: str
    snapshot_date: date
    horizon_days: int
    composite_score: float
    label: str
    confidence: float
    generated_at: datetime
    components: CompositeV2Components


class CompositeV2SnapshotResponse(BaseModel):
    snapshot_date: date
    horizon_days: int
    regime_score: float
    flow_score: float
    sentiment_score: Optional[float] = None
    risk_score: float
    regime_weight: float
    flow_weight: float
    sentiment_weight: float
    risk_weight: float
    composite_score: float
    label: str
    confidence: float
    generated_at: datetime


class BacktestV2Segment(BaseModel):
    segment: str
    samples: int
    avg_return_pct: Optional[float] = None
    return_std_pct: Optional[float] = None
    hit_rate: Optional[float] = None
    sharpe: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


class CompositeV2BacktestResponse(BaseModel):
    coingecko_id: str
    horizon_days: int
    generated_at: datetime
    total_samples: int
    bucket_segments: list[BacktestV2Segment]
    regime_segments: list[BacktestV2Segment]


class WalkForwardMonthResult(BaseModel):
    month: str
    train_samples: int
    test_samples: int
    active_signals: int
    avg_future_return_pct: Optional[float] = None
    avg_strategy_return_pct: Optional[float] = None
    hit_rate: Optional[float] = None
    sharpe: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    bucket_ge70_avg_return_pct: Optional[float] = None
    bucket_lt30_avg_return_pct: Optional[float] = None


class CompositeV2WalkForwardResponse(BaseModel):
    coingecko_id: str
    horizon_days: int
    lower_threshold: float
    upper_threshold: float
    min_train_months: int
    generated_at: datetime
    total_test_samples: int
    total_active_signals: int
    overall_avg_future_return_pct: Optional[float] = None
    overall_avg_strategy_return_pct: Optional[float] = None
    overall_hit_rate: Optional[float] = None
    overall_sharpe: Optional[float] = None
    overall_max_drawdown_pct: Optional[float] = None
    months: list[WalkForwardMonthResult]


class CompositeInterpretationResponse(BaseModel):
    coingecko_id: str
    generated_at: datetime
    horizon_days: int
    lower_threshold: float
    upper_threshold: float
    v1_score: float
    v1_label: str
    v2_score: float
    v2_label: str
    summary: str
    reasons: list[str]
    reliability: str
    policy_implication: str
    alerts: list[str]
    guardrails: list[str]


class CryptoProfileResponse(BaseModel):
    coingecko_id: str
    name: str
    symbol: str
    description: str
    homepage: Optional[str] = None
    genesis_date: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
