import { useCallback, useEffect, useMemo, useState } from 'react';
import './App.css';
import type { Cryptocurrency, PriceHistory } from './types';

const API_BASE = 'http://192.168.1.4:8000/api/v1';
const AUTH_STORAGE_KEY = 'tentaclelab_basic_auth';

interface CryptoData extends Cryptocurrency {
  history: PriceHistory[];
}

function App() {
  const [cryptos, setCryptos] = useState<CryptoData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [fullHistoryByCoin, setFullHistoryByCoin] = useState<Record<string, PriceHistory[]>>({});
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [authHeader, setAuthHeader] = useState<string>(() => localStorage.getItem(AUTH_STORAGE_KEY) ?? '');
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

  const formatCurrency = (value: number) => currencyFormatter.format(value);
  const formatDate = (value: string) => {
    const [year, month, day] = value.split('-').map(Number);
    return dateFormatter.format(new Date(year, month - 1, day));
  };

  const fetchWithAuth = useCallback(async (url: string) => {
    const response = await fetch(url, {
      headers: {
        Authorization: authHeader,
      },
    });
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('Sessao invalida. Faca login novamente.');
      }
      throw new Error(`HTTP error ${response.status}`);
    }
    return response;
  }, [authHeader]);

  const handleLogout = () => {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    setAuthHeader('');
    setCryptos([]);
    setSelectedId(null);
    setFullHistoryByCoin({});
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
        setLoginError('Usuario ou senha invalidos.');
        return;
      }

      localStorage.setItem(AUTH_STORAGE_KEY, header);
      setAuthHeader(header);
      setPassword('');
    } catch {
      setLoginError('Falha ao conectar no servidor.');
    } finally {
      setLoggingIn(false);
    }
  };

  const openCryptoDetail = async (crypto: CryptoData) => {
    setSelectedId(crypto.id);
    setDetailError(null);

    if (fullHistoryByCoin[crypto.coingecko_id]) {
      return;
    }

    try {
      setDetailLoading(true);
      const response = await fetchWithAuth(`${API_BASE}/cryptos/${crypto.coingecko_id}/history`);
      const fullHistory: PriceHistory[] = await response.json();
      setFullHistoryByCoin((prev) => ({ ...prev, [crypto.coingecko_id]: fullHistory }));
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Erro inesperado ao carregar historico completo';
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
        const cryptosResponse = await fetchWithAuth(`${API_BASE}/cryptos/`);
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
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Erro inesperado';
        if (message.includes('Sessao invalida')) {
          handleLogout();
        }
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    void fetchCryptoData();
  }, [authHeader, fetchWithAuth]);

  if (!authHeader) {
    return (
      <div className="app-state">
        <form className="login-card" onSubmit={handleLogin}>
          <h1>Entrar</h1>
          <p className="subtitle">Acesse o dashboard com usuario e senha.</p>
          <label htmlFor="username">Usuario</label>
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
          <p className="metric">Padrao inicial: admin / admin123</p>
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

  const selectedCrypto = cryptos.find((crypto) => crypto.id === selectedId) ?? null;

  if (selectedCrypto) {
    const history = fullHistoryByCoin[selectedCrypto.coingecko_id] ?? selectedCrypto.history;
    const currentPrice = history.length > 0 ? history[history.length - 1].price_usd : null;
    const maxPrice = history.length > 0 ? Math.max(...history.map((entry) => entry.price_usd)) : 0;
    const minPrice = history.length > 0 ? Math.min(...history.map((entry) => entry.price_usd)) : 0;
    const periodStart = history.length > 0 ? formatDate(history[0].date) : 'N/A';
    const periodEnd = history.length > 0 ? formatDate(history[history.length - 1].date) : 'N/A';
    const firstPrice = history.length > 0 ? history[0].price_usd : 0;
    const changePercent = firstPrice > 0 && currentPrice ? ((currentPrice - firstPrice) / firstPrice) * 100 : 0;
    const chartXStart = 8;
    const chartXEnd = 96;
    const chartYTop = 10;
    const chartYBottom = 84;
    const chartMid = (chartYTop + chartYBottom) / 2;
    const points =
      history.length > 1
        ? history
            .map((entry, index) => {
              const x = chartXStart + (index / (history.length - 1)) * (chartXEnd - chartXStart);
              const y =
                maxPrice === minPrice
                  ? chartMid
                  : chartYBottom - ((entry.price_usd - minPrice) / (maxPrice - minPrice)) * (chartYBottom - chartYTop);
              return `${x},${y}`;
            })
            .join(' ')
        : '';
    const areaPoints = points ? `${chartXStart},${chartYBottom} ${points} ${chartXEnd},${chartYBottom}` : '';
    const trendClass = changePercent >= 0 ? 'trend-up' : 'trend-down';
    const midValue = history.length > 0 ? (maxPrice + minPrice) / 2 : 0;

    return (
      <div className="app-shell">
        <header className="app-header detail-header">
          <div className="header-row">
            <button className="back-button" onClick={() => setSelectedId(null)}>
              Voltar para lista
            </button>
            <button className="logout-button" onClick={handleLogout}>
              Sair
            </button>
          </div>
          <div className="crypto-head">
            <img src={selectedCrypto.image_url} alt={selectedCrypto.name} className="crypto-logo" />
            <div>
              <h1>{selectedCrypto.name}</h1>
              <p className="subtitle">{selectedCrypto.symbol.toUpperCase()}</p>
            </div>
          </div>
        </header>

        <section className="detail-grid">
          <article className="crypto-card">
            <h3>Resumo</h3>
            <div className="price-now">
              <span>Preco atual</span>
              <strong>{currentPrice !== null ? formatCurrency(currentPrice) : 'N/A'}</strong>
            </div>
            <p className="metric">Periodo: {periodStart} ate {periodEnd}</p>
            <p className="metric">Maximo do periodo: {maxPrice ? formatCurrency(maxPrice) : 'N/A'}</p>
            <p className="metric">Minimo do periodo: {minPrice ? formatCurrency(minPrice) : 'N/A'}</p>
          </article>

          <article className="crypto-card">
            <h3>Predict (em breve)</h3>
            <p className="predict-copy">Aqui vamos exibir previsao com base em criterios que voce definir.</p>
            <ul className="predict-list">
              <li>Tendencia de preco (curto prazo)</li>
              <li>Volume e variacao de market cap</li>
              <li>Confluencia de indicadores tecnicos</li>
            </ul>
          </article>
        </section>

        <article className="crypto-card">
          <h3>Grafico de preco (toda a vida no banco)</h3>
          {detailLoading && <p className="metric">Carregando historico completo...</p>}
          {detailError && <p className="metric detail-error">{detailError}</p>}
          {history.length > 1 ? (
            <div className="chart-wrap">
              <div className="chart-meta">
                <span className={trendClass}>Variacao: {changePercent.toFixed(2)}%</span>
                <span>{history.length} pontos</span>
              </div>
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="price-chart" aria-label="Grafico de preco">
                <line x1={chartXStart} y1={chartYTop} x2={chartXEnd} y2={chartYTop} className="chart-grid" />
                <line x1={chartXStart} y1={chartMid} x2={chartXEnd} y2={chartMid} className="chart-grid" />
                <line x1={chartXStart} y1={chartYBottom} x2={chartXEnd} y2={chartYBottom} className="chart-grid" />
                <polygon points={areaPoints} className="chart-area" />
                <polyline points={points} fill="none" className="chart-line" />
                <text x={chartXStart} y={chartYTop - 1} className="chart-label">
                  {formatCurrency(maxPrice)}
                </text>
                <text x={chartXStart} y={chartMid - 1} className="chart-label">
                  {formatCurrency(midValue)}
                </text>
                <text x={chartXStart} y={chartYBottom + 5} className="chart-label">
                  {formatCurrency(minPrice)}
                </text>
              </svg>
              <div className="chart-footer">
                <span>{periodStart}</span>
                <span>{periodEnd}</span>
              </div>
            </div>
          ) : (
            <p className="metric">Dados insuficientes para grafico.</p>
          )}
        </article>

        <article className="crypto-card">
          <h3>Historico detalhado (toda a vida no banco)</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Preco</th>
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
    <div className="app-shell">
      <header className="app-header">
        <div className="header-row">
          <div>
            <h1>TentacleLab</h1>
            <p className="subtitle">Clique em uma moeda para abrir detalhes e area de predict.</p>
          </div>
          <button className="logout-button" onClick={handleLogout}>
            Sair
          </button>
        </div>
      </header>
      <div className="crypto-grid">
        {cryptos.map((crypto) => (
          <article key={crypto.id} className="crypto-card clickable-card" onClick={() => void openCryptoDetail(crypto)}>
            <div className="crypto-head">
              <img src={crypto.image_url} alt={crypto.name} className="crypto-logo" />
              <div>
                <h2>{crypto.name}</h2>
                <p className="symbol">{crypto.symbol.toUpperCase()}</p>
              </div>
            </div>

            <div className="price-now">
              <span>Preco atual</span>
              <strong>
                {crypto.history.length > 0 ? formatCurrency(crypto.history[crypto.history.length - 1].price_usd) : 'N/A'}
              </strong>
            </div>

            <h3>Historico (7 dias)</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Preco</th>
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
    </div>
  );
}

export default App;
