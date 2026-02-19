export type DetailTab = 'predicao' | 'estado' | 'composite';
export type AnalysisHorizon = '24h' | '7d' | '30d';

export interface PredictData {
  coingecko_id: string;
  horizon: string;
  signal: string;
  probability_up: number;
  confidence: number;
  generated_at: string;
  last_price_usd: number;
  features: {
    momentum_14d_pct: number;
    momentum_30d_pct: number;
    volatility_30d_pct: number;
    rsi_14: number;
    sma_20: number;
    sma_50: number;
    volume_zscore_30: number;
  };
}

export interface MarketStateData {
  coingecko_id: string;
  regime: string;
  probability_up: number;
  probability_flat: number;
  probability_down: number;
  risk_score: number;
  asymmetry_score: number;
  momentum_structural_score: number;
  volatility_future_7d_pct: number;
  volatility_future_30d_pct: number;
  confidence: number;
  generated_at: string;
  last_price_usd: number;
  components: {
    momentum_30d_pct: number;
    momentum_90d_pct: number;
    sma20_sma50_spread_pct: number;
    rsi_14: number;
    volatility_30d_pct: number;
    drawdown_180d_pct: number;
    volume_zscore_30: number;
  };
}

export interface CompositeData {
  coingecko_id: string;
  snapshot_date: string;
  horizon_days: number;
  composite_score: number;
  label: string;
  confidence: number;
  generated_at: string;
  components: {
    regime_score: number;
    flow_score: number;
    sentiment_score: number;
    sentiment_source: string;
  };
}
