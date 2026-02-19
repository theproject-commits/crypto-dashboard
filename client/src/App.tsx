import { useCallback, useEffect, useMemo, useState } from 'react';
import type { UTCTimestamp } from 'lightweight-charts';
import './App.css';
import type { Cryptocurrency, PriceHistory } from './types';
import type { AnalysisHorizon, CompositeData, DetailTab, MarketStateData, PredictData } from './analysis-types';
import { TradingPriceChart } from './components/TradingPriceChart';
import type { PriceLineSeries } from './components/TradingPriceChart';
import { TradingVolumeChart } from './components/TradingVolumeChart';
import { AnalysisPanel } from './components/AnalysisPanel';

const API_BASE = import.meta.env.VITE_API_BASE ?? `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;
const AUTH_STORAGE_KEY = 'tentaclelab_basic_auth';
const THEME_STORAGE_KEY = 'tentaclelab_theme';
const REQUEST_TIMEOUT_MS = 12000;

interface CryptoData extends Cryptocurrency {
  history: PriceHistory[];
}

type Theme = 'light' | 'dark';
type ListFilter = 'all' | 'top_gainers' | 'top_losers' | 'top_market_cap' | 'top_volume';
type ChartRange = 'LIVE' | '7D' | '30D' | '90D' | '1Y' | 'ALL';
type ChartPoint = PriceLineSeries['points'][number];

const CHART_RANGE_DAYS: Record<Exclude<ChartRange, 'ALL'>, number> = {
  LIVE: 30,
  '7D': 7,
  '30D': 30,
  '90D': 90,
  '1Y': 365,
};
const COMPARE_COLORS = ['#f59e0b', '#a78bfa', '#22c55e', '#ef4444', '#06b6d4'];
const LIVE_WINDOW_SECONDS = 3600;
const ANALYSIS_HORIZON_TO_COMPOSITE_DAYS: Record<AnalysisHorizon, number> = {
  '24h': 7,
  '7d': 7,
  '30d': 30,
};

function filterHistoryByRange(history: PriceHistory[], range: ChartRange): PriceHistory[] {
  if (range === 'ALL' || history.length <= 1) return history;
  const latest = history[history.length - 1];
  const [y, m, d] = latest.date.split('-').map(Number);
  const end = new Date(Date.UTC(y, m - 1, d));
  const cutoff = new Date(end);
  cutoff.setUTCDate(cutoff.getUTCDate() - CHART_RANGE_DAYS[range]);
  return history.filter((entry) => {
    const [ey, em, ed] = entry.date.split('-').map(Number);
    const dt = new Date(Date.UTC(ey, em - 1, ed));
    return dt >= cutoff;
  });
}

interface LivePoint {
  price_usd: number;
  fetched_at: string;
}

function historyToPoints(history: PriceHistory[]): ChartPoint[] {
  return history.map((entry) => {
    const [year, month, day] = entry.date.split('-').map(Number);
    return {
      time: { year, month, day },
      value: entry.price_usd,
    };
  });
}

function toUnixSeconds(value: string): UTCTimestamp | null {
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000) as UTCTimestamp;
}

function livePointsToChartPoints(points: LivePoint[]): ChartPoint[] {
  return points
    .map((entry) => {
      const ts = toUnixSeconds(entry.fetched_at);
      if (ts === null) return null;
      return {
        time: ts,
        value: entry.price_usd,
      } as ChartPoint;
    })
    .filter((entry): entry is ChartPoint => entry !== null);
}

function applyLivePoint(history: PriceHistory[], live: LivePoint | undefined): PriceHistory[] {
  if (!live || history.length === 0) return history;
  const date = live.fetched_at.split('T')[0];
  const updated = [...history];
  const last = updated[updated.length - 1];
  if (last.date === date) {
    updated[updated.length - 1] = { ...last, price_usd: live.price_usd };
    return updated;
  }
  updated.push({
    ...last,
    id: -Date.now(),
    date,
    price_usd: live.price_usd,
  });
  return updated;
}

function App() {
  const [cryptos, setCryptos] = useState<CryptoData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [fullHistoryByCoin, setFullHistoryByCoin] = useState<Record<string, PriceHistory[]>>({});
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [activeDetailTab, setActiveDetailTab] = useState<DetailTab | null>(null);
  const [analysisHorizon, setAnalysisHorizon] = useState<AnalysisHorizon>('24h');
  const [detailTabLoading, setDetailTabLoading] = useState(false);
  const [detailTabError, setDetailTabError] = useState<string | null>(null);
  const [predictByCoin, setPredictByCoin] = useState<Record<string, Partial<Record<AnalysisHorizon, PredictData>>>>({});
  const [stateByCoin, setStateByCoin] = useState<Record<string, MarketStateData>>({});
  const [compositeByCoin, setCompositeByCoin] = useState<Record<string, Partial<Record<AnalysisHorizon, CompositeData>>>>({});
  const [lastSyncAtByCoin, setLastSyncAtByCoin] = useState<Record<string, string>>({});

  const [authHeader, setAuthHeader] = useState<string>(() => localStorage.getItem(AUTH_STORAGE_KEY) ?? '');
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light'));
  const [currentTime, setCurrentTime] = useState<Date>(new Date());
  const [searchQuery, setSearchQuery] = useState('');
  const [listFilter, setListFilter] = useState<ListFilter>('all');
  const [chartRange, setChartRange] = useState<ChartRange>('ALL');
  const [liveByCoin, setLiveByCoin] = useState<Record<string, LivePoint>>({});
  const [liveTicksByCoin, setLiveTicksByCoin] = useState<Record<string, LivePoint[]>>({});
  const [liveStatus, setLiveStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle');
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveUpdatedAt, setLiveUpdatedAt] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareDraftId, setCompareDraftId] = useState('');
  const [compareError, setCompareError] = useState<string | null>(null);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  const currencyFormatter = useMemo(
    () =>
      new Intl.NumberFormat('pt-BR', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2,
      }),
    []
  );
  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      }),
    []
  );
  const dateTimeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    []
  );
  const clockFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('pt-BR', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }),
    []
  );

  const formatCurrency = (value: number) => currencyFormatter.format(value);
  const formatPercent = (value: number) => `${value.toFixed(2)}%`;
  const formatDateTime = (value: string) => dateTimeFormatter.format(new Date(value));
  const formattedClock = clockFormatter.format(currentTime);
  const formatMinutesAgo = (value: string | null) => {
    if (!value) return 'Atualizado recentemente';
    const ms = currentTime.getTime() - new Date(value).getTime();
    const minutes = Math.max(0, Math.floor(ms / 60000));
    if (minutes <= 1) return 'Atualizado há 1 min';
    return `Atualizado há ${minutes} min`;
  };
  const formatDate = (value: string) => {
    const [year, month, day] = value.split('-').map(Number);
    return dateFormatter.format(new Date(year, month - 1, day));
  };

  const fetchWithAuth = useCallback(async (url: string) => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(url, {
        headers: {
          Authorization: authHeader,
        },
        cache: 'no-store',
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error('Tempo limite de requisição excedido.');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('Sessão inválida. Faça login novamente.');
      }
      throw new Error(`HTTP error ${response.status}`);
    }
    return response;
  }, [authHeader]);

  const selectedCrypto = cryptos.find((crypto) => crypto.id === selectedId) ?? null;
  const visibleCryptos = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const matches = cryptos.filter((crypto) => {
      if (!query) return true;
      return (
        crypto.name.toLowerCase().includes(query) ||
        crypto.symbol.toLowerCase().includes(query) ||
        crypto.coingecko_id.toLowerCase().includes(query)
      );
    });

    const currentPrice = (crypto: CryptoData) =>
      crypto.history.length > 0 ? crypto.history[crypto.history.length - 1].price_usd : 0;
    const marketCap = (crypto: CryptoData) =>
      crypto.history.length > 0 ? crypto.history[crypto.history.length - 1].market_cap_usd : 0;
    const volume = (crypto: CryptoData) =>
      crypto.history.length > 0 ? crypto.history[crypto.history.length - 1].total_volume_usd : 0;
    const changePct = (crypto: CryptoData) => {
      if (crypto.history.length < 2) return 0;
      const first = crypto.history[0].price_usd;
      const last = currentPrice(crypto);
      return first > 0 ? ((last - first) / first) * 100 : 0;
    };

    const sorted = [...matches];
    if (listFilter === 'top_gainers') {
      sorted.sort((a, b) => changePct(b) - changePct(a));
    } else if (listFilter === 'top_losers') {
      sorted.sort((a, b) => changePct(a) - changePct(b));
    } else if (listFilter === 'top_market_cap') {
      sorted.sort((a, b) => marketCap(b) - marketCap(a));
    } else if (listFilter === 'top_volume') {
      sorted.sort((a, b) => volume(b) - volume(a));
    }

    return sorted;
  }, [cryptos, listFilter, searchQuery]);

  const loadDetailTabData = useCallback(async (coingeckoId: string, tab: DetailTab, horizon: AnalysisHorizon) => {
    setDetailTabError(null);
    setDetailTabLoading(true);
    try {
      if (tab === 'predicao') {
        const response = await fetchWithAuth(`${API_BASE}/cryptos/${coingeckoId}/predict?horizon=${horizon}`);
        const payload: PredictData = await response.json();
        setPredictByCoin((prev) => ({
          ...prev,
          [coingeckoId]: {
            ...(prev[coingeckoId] ?? {}),
            [horizon]: payload,
          },
        }));
      } else if (tab === 'estado') {
        const response = await fetchWithAuth(`${API_BASE}/cryptos/${coingeckoId}/state`);
        const payload: MarketStateData = await response.json();
        setStateByCoin((prev) => ({ ...prev, [coingeckoId]: payload }));
      } else {
        const compositeDays = ANALYSIS_HORIZON_TO_COMPOSITE_DAYS[horizon];
        try {
          const response = await fetchWithAuth(`${API_BASE}/cryptos/${coingeckoId}/composite/v2?horizon_days=${compositeDays}`);
          const payload: {
            coingecko_id: string;
            snapshot_date: string;
            horizon_days: number;
            composite_score: number;
            label: string;
            confidence: number;
            generated_at: string;
            components: { regime_score: number; flow_score: number; sentiment_score: number | null };
          } = await response.json();
          const normalized: CompositeData = {
            coingecko_id: payload.coingecko_id,
            snapshot_date: payload.snapshot_date,
            horizon_days: payload.horizon_days,
            composite_score: payload.composite_score,
            label: payload.label,
            confidence: payload.confidence,
            generated_at: payload.generated_at,
            components: {
              regime_score: payload.components.regime_score,
              flow_score: payload.components.flow_score,
              sentiment_score: payload.components.sentiment_score ?? 50,
              sentiment_source: payload.components.sentiment_score === null ? 'fallback' : 'v2',
            },
          };
          setCompositeByCoin((prev) => ({
            ...prev,
            [coingeckoId]: {
              ...(prev[coingeckoId] ?? {}),
              [horizon]: normalized,
            },
          }));
        } catch {
          const response = await fetchWithAuth(`${API_BASE}/cryptos/${coingeckoId}/composite`);
          const payload: CompositeData = await response.json();
          setCompositeByCoin((prev) => ({
            ...prev,
            [coingeckoId]: {
              ...(prev[coingeckoId] ?? {}),
              [horizon]: payload,
            },
          }));
        }
      }
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Erro inesperado ao carregar dados da aba';
      setDetailTabError(message);
    } finally {
      setDetailTabLoading(false);
    }
  }, [fetchWithAuth]);

  const handleDetailTabChange = useCallback((tab: DetailTab) => {
    setActiveDetailTab(tab);
    if (!selectedCrypto) return;
    const coinId = selectedCrypto.coingecko_id;
    const shouldLoad =
      (tab === 'predicao' && !predictByCoin[coinId]?.[analysisHorizon]) ||
      (tab === 'estado' && !stateByCoin[coinId]) ||
      (tab === 'composite' && !compositeByCoin[coinId]?.[analysisHorizon]);
    if (shouldLoad) {
      void loadDetailTabData(coinId, tab, analysisHorizon);
    }
  }, [analysisHorizon, compositeByCoin, loadDetailTabData, predictByCoin, selectedCrypto, stateByCoin]);

  const handleAnalysisHorizonChange = useCallback((horizon: AnalysisHorizon) => {
    setAnalysisHorizon(horizon);
    if (!selectedCrypto || !activeDetailTab) return;
    const coinId = selectedCrypto.coingecko_id;
    const shouldLoad =
      (activeDetailTab === 'predicao' && !predictByCoin[coinId]?.[horizon]) ||
      (activeDetailTab === 'estado' && !stateByCoin[coinId]) ||
      (activeDetailTab === 'composite' && !compositeByCoin[coinId]?.[horizon]);
    if (shouldLoad) {
      void loadDetailTabData(coinId, activeDetailTab, horizon);
    }
  }, [activeDetailTab, compositeByCoin, loadDetailTabData, predictByCoin, selectedCrypto, stateByCoin]);

  const ensureCoinHistory = useCallback(async (coingeckoId: string) => {
    if (fullHistoryByCoin[coingeckoId]) return;
    const response = await fetchWithAuth(`${API_BASE}/cryptos/${coingeckoId}/history`);
    const fullHistory: PriceHistory[] = await response.json();
    setFullHistoryByCoin((prev) => ({ ...prev, [coingeckoId]: fullHistory }));
    setLastSyncAtByCoin((prev) => ({ ...prev, [coingeckoId]: new Date().toISOString() }));
  }, [fetchWithAuth, fullHistoryByCoin]);

  const handleLogout = () => {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    setAuthHeader('');
    setCryptos([]);
    setSelectedId(null);
    setFullHistoryByCoin({});
    setLastSyncAtByCoin({});
    setLiveByCoin({});
    setLiveTicksByCoin({});
  };

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginError(null);
    setLoggingIn(true);

    const header = `Basic ${btoa(`${username}:${password}`)}`;
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        setLoginError('Usuário ou senha inválidos.');
        return;
      }

      localStorage.setItem(AUTH_STORAGE_KEY, header);
      setAuthHeader(header);
      setPassword('');
    } catch {
      setLoginError('Falha ao conectar ao servidor.');
    } finally {
      setLoggingIn(false);
    }
  };

  const openCryptoDetail = async (crypto: CryptoData) => {
    setSelectedId(crypto.id);
    setActiveDetailTab(null);
    setDetailTabError(null);
    setDetailError(null);
    setCompareIds([]);
    setCompareDraftId('');
    setCompareError(null);

    if (fullHistoryByCoin[crypto.coingecko_id]) return;

    try {
      setDetailLoading(true);
      const response = await fetchWithAuth(`${API_BASE}/cryptos/${crypto.coingecko_id}/history`);
      const fullHistory: PriceHistory[] = await response.json();
      setFullHistoryByCoin((prev) => ({ ...prev, [crypto.coingecko_id]: fullHistory }));
      setLastSyncAtByCoin((prev) => ({ ...prev, [crypto.coingecko_id]: new Date().toISOString() }));
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Erro inesperado ao carregar histórico completo';
      setDetailError(message);
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!authHeader) {
      return;
    }

    const fetchCryptoData = async () => {
      try {
        setLoading(true);
        setError(null);
        const cryptosResponse = await fetchWithAuth(`${API_BASE}/cryptos/?limit=25`);
        const cryptosList: Cryptocurrency[] = await cryptosResponse.json();

        const today = new Date();
        const endDate = today.toISOString().split('T')[0];
        const start = new Date(today);
        start.setDate(start.getDate() - 7);
        const startDate = start.toISOString().split('T')[0];

        const cryptosWithHistory = await Promise.all(
          cryptosList.map(async (crypto) => {
            const historyResponse = await fetchWithAuth(
              `${API_BASE}/cryptos/${crypto.coingecko_id}/history?start_date=${startDate}&end_date=${endDate}`
            );
            const history: PriceHistory[] = await historyResponse.json();
            return { ...crypto, history };
          })
        );
        setCryptos(cryptosWithHistory);
        const nowIso = new Date().toISOString();
        const syncMap = Object.fromEntries(cryptosWithHistory.map((crypto) => [crypto.coingecko_id, nowIso]));
        setLastSyncAtByCoin(syncMap);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Erro inesperado';
        if (message.includes('Sessão inválida')) {
          handleLogout();
        }
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    void fetchCryptoData();
  }, [authHeader, fetchWithAuth]);

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    document.body.classList.remove('app-theme-light', 'app-theme-dark');
    document.body.classList.add(theme === 'dark' ? 'app-theme-dark' : 'app-theme-light');
  }, [theme]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedCrypto || chartRange !== 'LIVE') return;
    let cancelled = false;

    const tick = async () => {
      const ids = [selectedCrypto.coingecko_id, ...compareIds];
      setLiveStatus('loading');
      setLiveError(null);
      try {
        const rows = await Promise.all(
          ids.map(async (id) => {
            const response = await fetchWithAuth(`${API_BASE}/cryptos/${id}/live?t=${Date.now()}`);
            const payload: { coingecko_id: string; price_usd: number; fetched_at: string } = await response.json();
            return payload;
          })
        );
        if (cancelled) return;
        setLiveByCoin((prev) => {
          const next = { ...prev };
          for (const row of rows) {
            next[row.coingecko_id] = { price_usd: row.price_usd, fetched_at: row.fetched_at };
          }
          return next;
        });
        setLiveTicksByCoin((prev) => {
          const next = { ...prev };
          const cutoffMs = Date.now() - LIVE_WINDOW_SECONDS * 1000;
          for (const row of rows) {
            const current = (next[row.coingecko_id] ?? []).filter((point) => {
              const ms = Date.parse(point.fetched_at);
              return Number.isFinite(ms) && ms >= cutoffMs;
            });
            const last = current[current.length - 1];
            const tickTime = !last || last.fetched_at !== row.fetched_at ? row.fetched_at : new Date().toISOString();
            next[row.coingecko_id] = [...current, { price_usd: row.price_usd, fetched_at: tickTime }];
          }
          return next;
        });
        setLiveStatus('ok');
        setLiveUpdatedAt(new Date().toISOString());
      } catch {
        if (cancelled) return;
        setLiveStatus('error');
        setLiveError('Falha ao atualizar LIVE. Verifique a conexão com a API.');
      }
    };

    void tick();
    const interval = window.setInterval(() => void tick(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [API_BASE, chartRange, compareIds, fetchWithAuth, selectedCrypto]);

  const selectedHistory = useMemo(() => {
    if (!selectedCrypto) return [] as PriceHistory[];
    return fullHistoryByCoin[selectedCrypto.coingecko_id] ?? selectedCrypto.history;
  }, [fullHistoryByCoin, selectedCrypto]);
  const selectedChartHistory = useMemo(
    () =>
      chartRange === 'LIVE'
        ? applyLivePoint(filterHistoryByRange(selectedHistory, 'LIVE'), selectedCrypto ? liveByCoin[selectedCrypto.coingecko_id] : undefined)
        : filterHistoryByRange(selectedHistory, chartRange),
    [chartRange, liveByCoin, selectedCrypto, selectedHistory]
  );
  const compareCandidates = useMemo(
    () => (selectedCrypto ? cryptos.filter((c) => c.coingecko_id !== selectedCrypto.coingecko_id) : []),
    [cryptos, selectedCrypto]
  );
  const compareSeriesOnly = useMemo(() => {
    if (!selectedCrypto) return [] as PriceLineSeries[];
    return compareIds
      .map((coingeckoId, idx) => {
            const compareHistorySource =
              fullHistoryByCoin[coingeckoId] ?? cryptos.find((c) => c.coingecko_id === coingeckoId)?.history ?? [];
            const filteredBase = filterHistoryByRange(compareHistorySource, chartRange === 'LIVE' ? 'LIVE' : chartRange);
            const filtered = chartRange === 'LIVE' ? applyLivePoint(filteredBase, liveByCoin[coingeckoId]) : filteredBase;
            const livePoints = livePointsToChartPoints(liveTicksByCoin[coingeckoId] ?? []);
            const points = chartRange === 'LIVE' ? livePoints : historyToPoints(filtered);
            if (points.length < 2) return null;
            return {
              id: coingeckoId,
              points,
              color: COMPARE_COLORS[idx % COMPARE_COLORS.length],
            };
          })
          .filter((x): x is PriceLineSeries => x !== null);
  }, [chartRange, compareIds, cryptos, fullHistoryByCoin, liveByCoin, liveTicksByCoin, selectedCrypto]);
  const selectedPricePoints = useMemo(() => {
    if (!selectedCrypto) return [] as ChartPoint[];
    const livePoints = livePointsToChartPoints(liveTicksByCoin[selectedCrypto.coingecko_id] ?? []);
    if (chartRange === 'LIVE') return livePoints;
    return historyToPoints(selectedChartHistory);
  }, [chartRange, liveTicksByCoin, selectedChartHistory, selectedCrypto]);
  const primarySeries = useMemo(
    () => [{ id: 'primary', points: selectedPricePoints, color: '#22d3ee' }] as PriceLineSeries[],
    [selectedPricePoints]
  );
  const comparisonSeries = useMemo(
    () => [...primarySeries, ...compareSeriesOnly],
    [compareSeriesOnly, primarySeries]
  );

  if (!authHeader) {
    return (
      <div className="app-state">
        <form className="login-card" onSubmit={handleLogin}>
          <h1>Entrar</h1>
          <p className="subtitle">Acesse o dashboard com usuário e senha.</p>
          <label htmlFor="username">Usuário</label>
          <input
            id="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
          <label htmlFor="password">Senha</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
          {loginError && <p className="detail-error">{loginError}</p>}
          <button className="detail-button" type="submit" disabled={loggingIn}>
            {loggingIn ? 'Entrando...' : 'Entrar'}
          </button>
          <p className="metric">Padrão inicial: admin / admin123</p>
        </form>
      </div>
    );
  }

  if (loading) {
    return <div className="app-state">Carregando dados das criptomoedas...</div>;
  }

  if (error) {
    return <div className="app-state error">Erro ao carregar dados: {error}</div>;
  }

  if (selectedCrypto) {
    const history = selectedHistory;
    const chartHistory = selectedChartHistory;
    const currentPriceRaw = history.length > 0 ? history[history.length - 1].price_usd : null;
    const currentPriceLive = liveByCoin[selectedCrypto.coingecko_id]?.price_usd ?? null;
    const currentPrice = chartRange === 'LIVE' && currentPriceLive !== null ? currentPriceLive : currentPriceRaw;
    const maxPrice = history.length > 0 ? Math.max(...history.map((entry) => entry.price_usd)) : 0;
    const minPrice = history.length > 0 ? Math.min(...history.map((entry) => entry.price_usd)) : 0;
    const periodStart = history.length > 0 ? formatDate(history[0].date) : 'N/A';
    const periodEnd = history.length > 0 ? formatDate(history[history.length - 1].date) : 'N/A';
    const formatChartPointLabel = (point: ChartPoint) => {
      if (typeof point.time === 'number') return formatDateTime(new Date(point.time * 1000).toISOString());
      const { year, month, day } = point.time;
      return formatDate(`${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`);
    };
    const chartPeriodStart = selectedPricePoints.length > 0 ? formatChartPointLabel(selectedPricePoints[0]) : 'N/A';
    const chartPeriodEnd = selectedPricePoints.length > 0 ? formatChartPointLabel(selectedPricePoints[selectedPricePoints.length - 1]) : 'N/A';
    const firstPrice = history.length > 0 ? history[0].price_usd : 0;
    const changePercent = firstPrice > 0 && currentPrice ? ((currentPrice - firstPrice) / firstPrice) * 100 : 0;
    const trendClass = changePercent >= 0 ? 'trend-up' : 'trend-down';
    const predict = predictByCoin[selectedCrypto.coingecko_id]?.[analysisHorizon];
    const state = stateByCoin[selectedCrypto.coingecko_id];
    const composite = compositeByCoin[selectedCrypto.coingecko_id]?.[analysisHorizon];
    const predictPrice = predict?.last_price_usd ?? null;
    const predictSma20 = predict?.features.sma_20 ?? null;
    const predictSma50 = predict?.features.sma_50 ?? null;
    const distanceToSma20 = predictPrice !== null && predictSma20 !== null && predictSma20 > 0
      ? ((predictPrice - predictSma20) / predictSma20) * 100
      : null;
    const distanceToSma50 = predictPrice !== null && predictSma50 !== null && predictSma50 > 0
      ? ((predictPrice - predictSma50) / predictSma50) * 100
      : null;
    const spreadSma20Sma50 = predictSma20 !== null && predictSma50 !== null && predictSma50 > 0
      ? ((predictSma20 - predictSma50) / predictSma50) * 100
      : null;
    const predictRsi = predict?.features.rsi_14 ?? null;
    const predictRsiLabel = predictRsi !== null
      ? (predictRsi >= 70 ? 'Sobrecompra' : predictRsi <= 30 ? 'Sobrevenda' : 'Neutro')
      : null;
    const predictVolumeZ = predict?.features.volume_zscore_30 ?? null;
    const predictVolumeLabel = predictVolumeZ !== null
      ? (predictVolumeZ >= 1.5 ? 'Volume alto' : predictVolumeZ <= -1.5 ? 'Volume baixo' : 'Volume normal')
      : null;
    const toneBySign = (value: number | null) => {
      if (value === null) return 'tone-neutral';
      if (value > 0) return 'tone-positive';
      if (value < 0) return 'tone-negative';
      return 'tone-neutral';
    };
    const signalTone =
      predict?.signal === 'strong_buy' || predict?.signal === 'buy'
        ? 'tone-positive'
        : predict?.signal === 'strong_sell' || predict?.signal === 'sell'
          ? 'tone-negative'
          : 'tone-neutral';
    const probabilityTone = predict
      ? (predict.probability_up >= 0.56 ? 'tone-positive' : predict.probability_up <= 0.44 ? 'tone-negative' : 'tone-neutral')
      : 'tone-neutral';
    const confidenceTone = predict ? (predict.confidence >= 0.4 ? 'tone-strong' : 'tone-neutral') : 'tone-neutral';
    const rsiTone = predictRsi !== null ? (predictRsi >= 70 ? 'tone-negative' : predictRsi <= 30 ? 'tone-positive' : 'tone-neutral') : 'tone-neutral';
    const volumeTone = predictVolumeZ !== null ? (predictVolumeZ >= 1.5 ? 'tone-positive' : predictVolumeZ <= -1.5 ? 'tone-negative' : 'tone-neutral') : 'tone-neutral';

    const lastSyncLabel = formatMinutesAgo(
      chartRange === 'LIVE'
        ? (liveUpdatedAt ?? liveByCoin[selectedCrypto.coingecko_id]?.fetched_at ?? null)
        : (lastSyncAtByCoin[selectedCrypto.coingecko_id] ?? null)
    );
    const chartChangePercent = (() => {
      if (chartHistory.length < 2) return null;
      const first = chartHistory[0].price_usd;
      const last = chartHistory[chartHistory.length - 1].price_usd;
      if (first <= 0) return null;
      return ((last - first) / first) * 100;
    })();
    return (
      <div className={`app-shell ${theme === 'dark' ? 'theme-dark' : 'theme-light'}`}>
        <section className="detail-top-grid">
          <article className="app-header top-card">
            <div className="top-controls-row">
            <button className="back-button" onClick={() => setSelectedId(null)}>
              Voltar para lista
            </button>
            <div className="header-actions">
              <p className="dashboard-clock">Hora {formattedClock}</p>
              <button className="theme-button" onClick={() => setTheme((prev) => (prev === 'light' ? 'dark' : 'light'))}>
                {theme === 'light' ? 'Tema escuro' : 'Tema claro'}
              </button>
              <button className="logout-button" onClick={handleLogout}>
                Sair
              </button>
            </div>
            </div>
          </article>

          <article className="app-header top-card">
            <div className="asset-row">
              <div className="crypto-head">
                <img src={selectedCrypto.image_url} alt={selectedCrypto.name} className="crypto-logo" />
                <div>
                  <h1>{selectedCrypto.name}</h1>
                  <p className="subtitle">{selectedCrypto.symbol.toUpperCase()}</p>
                </div>
              </div>
              <div className="asset-price-box">
                <span className="asset-price-label">Preço atual</span>
                <strong className="asset-price-value">{currentPrice !== null ? formatCurrency(currentPrice) : 'N/A'}</strong>
                <span className="asset-updated">{lastSyncLabel}</span>
              </div>
            </div>
          </article>
        </section>

        <section className="detail-grid">
          <article className="crypto-card">
            <h3>Visão Geral</h3>
            <div className="price-now">
              <span>Preço atual</span>
              <strong>{currentPrice !== null ? formatCurrency(currentPrice) : 'N/A'}</strong>
            </div>
            <div className="kpi-grid">
              <div className={`kpi-card ${changePercent >= 2 ? 'is-positive' : changePercent <= -2 ? 'is-negative' : 'is-neutral'}`}>
                <span className="kpi-label">Variação</span>
                <strong className="kpi-value">{changePercent.toFixed(2)}%</strong>
              </div>
              <div className={`kpi-card ${history.length > 1000 ? 'is-positive' : 'is-neutral'}`}>
                <span className="kpi-label with-help">
                  <span>Pontos</span>
                  <span className="help-tooltip">
                    <button type="button" className="help-icon" aria-label="Explicacao de pontos">
                      ?
                    </button>
                    <span className="help-tooltip-bubble" role="tooltip">
                      Total de candles observados no historico desta moeda no periodo carregado.
                    </span>
                  </span>
                </span>
                <strong className="kpi-value">{history.length}</strong>
              </div>
            </div>
            <div className="stats-list">
              <p className="stats-row">
                <span className="stats-label">Período</span>
                <span className="stats-value">{periodStart} a {periodEnd}</span>
              </p>
              <p className="stats-row">
                <span className="stats-label">Máximo no período</span>
                <span className="stats-value">{maxPrice ? formatCurrency(maxPrice) : 'N/A'}</span>
              </p>
              <p className="stats-row">
                <span className="stats-label">Mínimo no período</span>
                <span className="stats-value">{minPrice ? formatCurrency(minPrice) : 'N/A'}</span>
              </p>
              <p className="stats-row">
                <span className="stats-label">Variação acumulada</span>
                <span className={`stats-value ${trendClass}`}>{changePercent.toFixed(2)}%</span>
              </p>
              <p className="stats-row">
                <span className="stats-label">Pontos históricos</span>
                <span className="stats-value">{history.length}</span>
              </p>
            </div>
          </article>

          <article className="crypto-card">
            <AnalysisPanel
              activeDetailTab={activeDetailTab}
              analysisHorizon={analysisHorizon}
              onTabChange={handleDetailTabChange}
              onHorizonChange={handleAnalysisHorizonChange}
            />
          </article>
        </section>

        <article className="crypto-card">
          <h3>{activeDetailTab === 'predicao' ? 'Features Técnicas' : activeDetailTab === 'estado' ? 'Estado de Mercado' : activeDetailTab === 'composite' ? 'Composite' : 'Análise'}</h3>
          {detailTabLoading && <p className="metric">Carregando dados da aba...</p>}
          {detailTabError && <p className="metric detail-error">{detailTabError}</p>}
          {!activeDetailTab && <p className="metric">Selecione uma aba de análise acima.</p>}

          {!detailTabLoading && !detailTabError && activeDetailTab === 'predicao' && predict && (
            <div className="stats-list analysis-enhanced">
              <p className="stats-row"><span className="stats-label">Signal</span><span className={`stats-value value-pill ${signalTone}`}>{predict.signal}</span></p>
              <p className="stats-row"><span className="stats-label">Horizonte</span><span className="stats-value value-pill tone-neutral">{predict.horizon}</span></p>
              <p className="stats-row"><span className="stats-label">Preço atual</span><span className="stats-value value-pill tone-strong">{predictPrice !== null ? formatCurrency(predictPrice) : 'N/A'}</span></p>
              <p className="stats-row"><span className="stats-label">Probabilidade de alta</span><span className={`stats-value value-pill ${probabilityTone}`}>{formatPercent(predict.probability_up * 100)}</span></p>
              <p className="stats-row"><span className="stats-label">Confiança</span><span className={`stats-value value-pill ${confidenceTone}`}>{formatPercent(predict.confidence * 100)}</span></p>
              <div className="kpi-grid">
                <div className={`kpi-card ${predict.features.sma_20 >= predict.features.sma_50 ? 'is-positive' : 'is-negative'}`}>
                  <span className="kpi-label">SMA 20</span>
                  <strong className="kpi-value">{formatCurrency(predict.features.sma_20)}</strong>
                </div>
                <div className={`kpi-card ${predict.features.sma_50 > predict.features.sma_20 ? 'is-positive' : 'is-neutral'}`}>
                  <span className="kpi-label">SMA 50</span>
                  <strong className="kpi-value">{formatCurrency(predict.features.sma_50)}</strong>
                </div>
              </div>
              <p className="stats-row"><span className="stats-label">Distância para SMA20</span><span className={`stats-value value-pill ${toneBySign(distanceToSma20)}`}>{distanceToSma20 !== null ? formatPercent(distanceToSma20) : 'N/A'}</span></p>
              <p className="stats-row"><span className="stats-label">Distância para SMA50</span><span className={`stats-value value-pill ${toneBySign(distanceToSma50)}`}>{distanceToSma50 !== null ? formatPercent(distanceToSma50) : 'N/A'}</span></p>
              <p className="stats-row"><span className="stats-label">Spread SMA20-SMA50</span><span className={`stats-value value-pill ${toneBySign(spreadSma20Sma50)}`}>{spreadSma20Sma50 !== null ? formatPercent(spreadSma20Sma50) : 'N/A'}</span></p>
              <p className="stats-row"><span className="stats-label">Momentum 14d / 30d</span><span className="stats-value value-pill tone-neutral">{formatPercent(predict.features.momentum_14d_pct)} / {formatPercent(predict.features.momentum_30d_pct)}</span></p>
              <p className="stats-row"><span className="stats-label">Volatilidade 30d</span><span className="stats-value value-pill tone-neutral">{formatPercent(predict.features.volatility_30d_pct)}</span></p>
              <p className="stats-row"><span className="stats-label">Volume z-score 30</span><span className={`stats-value value-pill ${volumeTone}`}>{predictVolumeZ !== null ? `${predictVolumeZ.toFixed(2)} (${predictVolumeLabel})` : 'N/A'}</span></p>
              <p className="stats-row"><span className="stats-label">RSI 14</span><span className={`stats-value value-pill ${rsiTone}`}>{predictRsi !== null ? `${predictRsi.toFixed(2)} (${predictRsiLabel})` : 'N/A'}</span></p>
              <p className="stats-row"><span className="stats-label">Atualizado em</span><span className="stats-value value-pill tone-neutral">{formatDateTime(predict.generated_at)}</span></p>
            </div>
          )}

          {!detailTabLoading && !detailTabError && activeDetailTab === 'estado' && state && (
            <div className="stats-list analysis-enhanced">
              <p className="stats-row"><span className="stats-label">Horizonte</span><span className="stats-value value-pill tone-neutral">{analysisHorizon}</span></p>
              <p className="stats-row"><span className="stats-label">Regime</span><span className="stats-value value-pill tone-neutral">{state.regime}</span></p>
              <p className="stats-row"><span className="stats-label">Alta / Lateral / Queda</span><span className="stats-value value-pill tone-neutral">{formatPercent(state.probability_up * 100)} / {formatPercent(state.probability_flat * 100)} / {formatPercent(state.probability_down * 100)}</span></p>
              <p className="stats-row"><span className="stats-label">Risco</span><span className="stats-value value-pill tone-neutral">{state.risk_score.toFixed(2)}</span></p>
              <p className="stats-row"><span className="stats-label">Momentum estrutural</span><span className="stats-value value-pill tone-neutral">{state.momentum_structural_score.toFixed(2)}</span></p>
              <p className="stats-row"><span className="stats-label">Volatilidade futura 30d</span><span className="stats-value value-pill tone-neutral">{formatPercent(state.volatility_future_30d_pct)}</span></p>
            </div>
          )}

          {!detailTabLoading && !detailTabError && activeDetailTab === 'composite' && composite && (
            <div className="stats-list analysis-enhanced">
              <p className="stats-row"><span className="stats-label">Horizonte</span><span className="stats-value value-pill tone-neutral">{analysisHorizon}</span></p>
              <p className="stats-row"><span className="stats-label">Score</span><span className="stats-value value-pill tone-strong">{composite.composite_score.toFixed(2)}</span></p>
              <p className="stats-row"><span className="stats-label">Label</span><span className="stats-value value-pill tone-neutral">{composite.label}</span></p>
              <p className="stats-row"><span className="stats-label">Confiança</span><span className="stats-value">{formatPercent(composite.confidence * 100)}</span></p>
              <p className="stats-row"><span className="stats-label">Horizonte (dias)</span><span className="stats-value value-pill tone-neutral">{composite.horizon_days}</span></p>
              <p className="stats-row"><span className="stats-label">Regime / Flow / Sentimento</span><span className="stats-value value-pill tone-neutral">{composite.components.regime_score.toFixed(1)} / {composite.components.flow_score.toFixed(1)} / {composite.components.sentiment_score.toFixed(1)}</span></p>
            </div>
          )}

          {!detailTabLoading && !detailTabError && activeDetailTab && ((activeDetailTab === 'predicao' && !predict) || (activeDetailTab === 'estado' && !state) || (activeDetailTab === 'composite' && !composite)) && (
            <p className="metric">Sem dados para essa aba.</p>
          )}
        </article>

        {(
          <article className="crypto-card">
            <h3>Evolução do Preço (Histórico Completo)</h3>
            {detailLoading && <p className="metric">Carregando histórico completo...</p>}
            {detailError && <p className="metric detail-error">{detailError}</p>}
            {(chartRange === 'LIVE' ? selectedPricePoints.length > 1 : chartHistory.length > 1) ? (
              <>
                <div className="compare-panel">
                  <div className="compare-row">
                    <select
                      className="filter-select"
                      value={compareDraftId}
                      onChange={(event) => setCompareDraftId(event.target.value)}
                    >
                      <option value="">Comparar com...</option>
                      {compareCandidates.map((coin) => (
                        <option key={coin.coingecko_id} value={coin.coingecko_id}>
                          {coin.name} ({coin.symbol.toUpperCase()})
                        </option>
                      ))}
                    </select>
                    <button
                      className="theme-button"
                      onClick={async () => {
                        if (!compareDraftId || compareIds.includes(compareDraftId) || compareIds.length >= 5) return;
                        setCompareError(null);
                        try {
                          await ensureCoinHistory(compareDraftId);
                          setCompareIds((prev) => [...prev, compareDraftId]);
                          setCompareDraftId('');
                        } catch (e: unknown) {
                          const msg = e instanceof Error ? e.message : 'Erro ao carregar cripto para comparação.';
                          setCompareError(msg);
                        }
                      }}
                    >
                      Adicionar
                    </button>
                  </div>
                  {compareError && <p className="metric detail-error">{compareError}</p>}
                  {compareIds.length > 0 && (
                    <div className="compare-chip-row">
                      {compareIds.map((id) => {
                        const coin = cryptos.find((c) => c.coingecko_id === id);
                        if (!coin) return null;
                        return (
                          <button
                            key={id}
                            className="compare-chip"
                            onClick={() => setCompareIds((prev) => prev.filter((x) => x !== id))}
                          >
                            {coin.symbol.toUpperCase()} x
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="range-row">
                  {(['LIVE', '7D', '30D', '90D', '1Y', 'ALL'] as ChartRange[]).map((range) => (
                    <button
                      key={range}
                      className={`range-button ${chartRange === range ? 'active' : ''}`}
                      onClick={() => setChartRange(range)}
                    >
                      {range === 'ALL' ? 'ALL TIME' : range}
                    </button>
                  ))}
                </div>
                {chartRange === 'LIVE' && (
                  <p className={`metric ${liveStatus === 'error' ? 'detail-error' : ''}`}>
                    LIVE: {liveStatus === 'loading' ? 'atualizando...' : liveStatus === 'ok' ? 'ativo' : liveStatus === 'error' ? 'erro' : 'aguardando'}{' '}
                    {liveUpdatedAt ? `| última atualização: ${formatDateTime(liveUpdatedAt)}` : ''}
                    {liveError ? ` | ${liveError}` : ''}
                  </p>
                )}
                <div className="chart-wrap">
                  <div className="chart-meta">
                    <span className={trendClass}>
                      Variação: {chartChangePercent === null ? 'N/A' : `${chartChangePercent.toFixed(2)}%`}
                    </span>
                    <span>{chartHistory.length} pontos</span>
                  </div>
                  <TradingPriceChart
                    series={primarySeries}
                    liveWindowSeconds={chartRange === 'LIVE' ? LIVE_WINDOW_SECONDS : undefined}
                  />
                  <div className="chart-footer">
                    <span>{chartPeriodStart}</span>
                    <span>{chartPeriodEnd}</span>
                  </div>
                </div>
                {compareSeriesOnly.length > 0 && (
                  <div className="chart-wrap compare-chart-wrap">
                    <div className="chart-meta">
                      <span>Comparação relativa (%)</span>
                      <span>{comparisonSeries.length} ativos</span>
                    </div>
                    <TradingPriceChart
                      series={comparisonSeries}
                      normalized
                      liveWindowSeconds={chartRange === 'LIVE' ? LIVE_WINDOW_SECONDS : undefined}
                    />
                    <div className="chart-legend">
                      <span className="legend-item">
                        <i className="legend-dot" style={{ backgroundColor: '#22d3ee' }} />
                        {selectedCrypto.symbol.toUpperCase()}
                      </span>
                      {compareIds.map((id, idx) => {
                        const coin = cryptos.find((c) => c.coingecko_id === id);
                        if (!coin) return null;
                        return (
                          <span key={id} className="legend-item">
                            <i className="legend-dot" style={{ backgroundColor: COMPARE_COLORS[idx % COMPARE_COLORS.length] }} />
                            {coin.symbol.toUpperCase()}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
                <div className="volume-wrap">
                  <p className="volume-title">Volume</p>
                  <TradingVolumeChart history={chartHistory} />
                </div>
              </>
            ) : (
              <p className="metric">
                {chartRange === 'LIVE' ? 'LIVE aguardando pontos suficientes (janela de 1h).' : 'Dados insuficientes para gráfico.'}
              </p>
            )}
          </article>
        )}
        <article className="crypto-card">
          <h3>Histórico Detalhado (Base Completa)</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Preço</th>
                  <th>Market Cap</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={entry.id}>
                    <td>{formatDate(entry.date)}</td>
                    <td>{formatCurrency(entry.price_usd)}</td>
                    <td>{formatCurrency(entry.market_cap_usd)}</td>
                    <td>{formatCurrency(entry.total_volume_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </div>
    );
  }

  return (
    <div className={`app-shell ${theme === 'dark' ? 'theme-dark' : 'theme-light'}`}>
      <header className="app-header">
        <div className="header-row">
          <div>
            <h1>TentacleLab</h1>
            <p className="subtitle">Clique em uma moeda para abrir detalhes e análise.</p>
          </div>
          <div className="header-actions">
            <p className="dashboard-clock">Hora {formattedClock}</p>
            <button className="theme-button" onClick={() => setTheme((prev) => (prev === 'light' ? 'dark' : 'light'))}>
              {theme === 'light' ? 'Tema escuro' : 'Tema claro'}
            </button>
            <button className="logout-button" onClick={handleLogout}>
              Sair
            </button>
          </div>
        </div>
      </header>
      <section className="list-toolbar">
        <input
          className="search-input"
          type="text"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Buscar por nome, símbolo ou id (ex: bitcoin, btc)"
        />
        <select
          className="filter-select"
          value={listFilter}
          onChange={(event) => setListFilter(event.target.value as ListFilter)}
        >
          <option value="all">Todos</option>
          <option value="top_gainers">Top gainers (7d)</option>
          <option value="top_losers">Top losers (7d)</option>
          <option value="top_market_cap">Top market cap</option>
          <option value="top_volume">Top volume</option>
        </select>
      </section>
      <div className="crypto-grid">
        {visibleCryptos.map((crypto) => (
          <article key={crypto.id} className="crypto-card clickable-card" onClick={() => void openCryptoDetail(crypto)}>
            <div className="crypto-head">
              <img src={crypto.image_url} alt={crypto.name} className="crypto-logo" />
              <div>
                <h2>{crypto.name}</h2>
                <p className="symbol">{crypto.symbol.toUpperCase()}</p>
              </div>
            </div>

            <div className="price-now">
              <span>Preço atual</span>
              <strong>
                {crypto.history.length > 0 ? formatCurrency(crypto.history[crypto.history.length - 1].price_usd) : 'N/A'}
              </strong>
            </div>

            <h3>Histórico (7 dias)</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Preço</th>
                    <th>Market Cap</th>
                    <th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {crypto.history.map((entry) => (
                    <tr key={entry.id}>
                      <td>{formatDate(entry.date)}</td>
                      <td>{formatCurrency(entry.price_usd)}</td>
                      <td>{formatCurrency(entry.market_cap_usd)}</td>
                      <td>{formatCurrency(entry.total_volume_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              className="detail-button"
              onClick={(event) => {
                event.stopPropagation();
                void openCryptoDetail(crypto);
              }}
            >
              Abrir detalhes
            </button>
          </article>
        ))}
      </div>
      {visibleCryptos.length === 0 && <p className="metric">Nenhuma moeda encontrada para esse filtro/busca.</p>}
    </div>
  );
}

export default App;
