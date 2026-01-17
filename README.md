# Crypto Dashboard & Prediction

Este projeto é um dashboard para visualização de dados de criptomoedas em tempo real, com um roadmap que inclui a implementação de modelos de Machine Learning para predição de valores.

## Arquitetura Técnica

O projeto será desenvolvido utilizando uma arquitetura de monorepo, separando o `client` (frontend) do `server` (backend).

### Frontend (Client)

- **Framework:** React com TypeScript
- **Build Tool:** Vite
- **Estilização:** TailwindCSS
- **Gráficos:** Chart.js ou uma biblioteca similar

O frontend será uma Single Page Application (SPA) responsável por apresentar os dados aos usuários de forma interativa. Ele consumirá a API REST fornecida pelo backend.

### Backend (Server)

- **Linguagem:** Python
- **Framework:** FastAPI
- **Banco de Dados:** PostgreSQL (recomendado) ou SQLite para desenvolvimento local.

O backend atuará como um intermediário entre o cliente e as APIs externas de criptomoedas. Suas responsabilidades incluem:

1.  **Proxy de API:** Centralizar as chamadas às APIs de cripto, protegendo chaves de acesso e reduzindo a carga no cliente.
2.  **Servir Dados:** Fornecer endpoints RESTful para o frontend.
3.  **Coleta e Armazenamento:** Gerenciar a coleta de dados de APIs externas e armazená-los no banco de dados.
4.  **Serviço de Predição (Futuro):** Expor um endpoint que retorne as predições geradas pelo modelo de Machine Learning.

## Estrutura de Pastas

```
/
├── client/         # Aplicação Frontend (React)
│   ├── src/
│   └── package.json
├── server/         # Aplicação Backend (Python/FastAPI)
│   ├── venv/       # Ambiente virtual Python
│   ├── src/        # Código fonte do backend
│   └── requirements.txt
└── README.md
```

## APIs de Criptomoedas

Utilizaremos a API da **CoinGecko** devido ao seu plano gratuito generoso e à disponibilidade de dados históricos.

**Endpoints Chave:**

-   `/coins/markets`: Para obter a lista das principais criptomoedas com dados de mercado atuais (preço, variação 24h, etc.).
-   `/coins/{id}/market_chart`: Para obter dados históricos (preço, capitalização, volume) de uma moeda específica.

### Estratégias de Rate Limiting

É crucial respeitar os limites de requisições das APIs para evitar bloqueios.

-   **No Script de Coleta (`server/src/scripts/populate_db.py`):**
    *   Implementaremos pausas (`time.sleep()`) entre as requisições à API da CoinGecko para garantir que não excedamos o limite de ~50 chamadas por minuto.
-   **No Backend da API (FastAPI):**
    *   Para dados que não necessitam de atualização a cada segundo (ex: lista de moedas, dados de mercado gerais), implementaremos um **cache** in-memory ou via Redis. Isso significa que, após a primeira requisição, os dados serão armazenados temporariamente, e requisições subsequentes receberão os dados cacheados em vez de fazer uma nova chamada à API externa, reduzindo drasticamente o número de chamadas à CoinGecko.

## Modelo de Dados (Banco de Dados)

Para persistir os dados coletados, usaremos um banco de dados relacional (PostgreSQL recomendado).

### Tabela: `cryptocurrencies`

Armazena informações básicas sobre cada criptomoeda.

| Coluna         | Tipo de Dado         | Descrição                                 |
| :------------- | :------------------- | :---------------------------------------- |
| `id`           | SERIAL PRIMARY KEY   | Identificador único interno.              |
| `coingecko_id` | VARCHAR(50) UNIQUE   | ID da moeda na CoinGecko (ex: 'bitcoin'). |
| `symbol`       | VARCHAR(10)          | Símbolo da moeda (ex: 'btc').             |
| `name`         | VARCHAR(100)         | Nome completo da moeda (ex: 'Bitcoin').   |
| `image_url`    | VARCHAR(255)         | URL da imagem do logo da moeda.           |
| `last_updated` | TIMESTAMP            | Última vez que as informações foram atualizadas. |

### Tabela: `price_history`

Armazena dados históricos diários para cada criptomoeda.

| Coluna           | Tipo de Dado         | Descrição                                   |
| :--------------- | :------------------- | :------------------------------------------ |
| `id`             | SERIAL PRIMARY KEY   | Identificador único interno.                |
| `crypto_id`      | INTEGER (FOREIGN KEY)| Referência ao `id` da `cryptocurrencies`.   |
| `date`           | DATE                 | Data da medição (UTC).                      |
| `price_usd`      | DECIMAL(20, 10)      | Preço de fechamento em USD.                 |
| `market_cap_usd` | BIGINT               | Capitalização de mercado em USD.            |
| `total_volume_usd`| BIGINT              | Volume total de negociação em USD.          |
| `created_at`     | TIMESTAMP            | Timestamp da criação do registro.           |

## Como Começar (Setup Inicial)

### Pré-requisitos

- Node.js (v18 ou superior) para o frontend
- npm ou yarn para o frontend
- Python (v3.9 ou superior) para o backend
- pip ou pipenv/poetry para gerenciamento de pacotes Python
- PostgreSQL (opcional, para ambiente de produção/desenvolvimento)

### Configuração do Backend (Python/FastAPI)

1.  Navegue até a pasta `server`:
    ```bash
    cd server
    ```
2.  Crie e ative um ambiente virtual:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # No Windows, use `venv\Scripts\activate`
    ```
3.  Instale as dependências:
    ```bash
    pip install -r requirements.txt
    ```
    *(O arquivo `requirements.txt` será criado na próxima etapa.)*
4.  Crie um arquivo `.env` na raiz da pasta `server` para suas variáveis de ambiente:
    ```
    # Exemplo de chave de API (se necessário, a CoinGecko geralmente não exige para endpoints públicos)
    # COINGECKO_API_KEY=sua_chave_de_api_aqui

    # Configuração do Banco de Dados (exemplo para PostgreSQL)
    DATABASE_URL="postgresql://user:password@host:port/database_name"
    ```
5.  Para iniciar o servidor de desenvolvimento (depois de criar `src/main.py`):
    ```bash
    uvicorn src.main:app --reload
    ```

### Configuração do Frontend (React/Vite)

1.  Em outro terminal, navegue até a pasta `client`:
    ```bash
    cd client
    ```
2.  Instale as dependências:
    ```bash
    npm install
    ```
3.  Inicie o cliente de desenvolvimento:
    ```bash
    npm run dev
    ```
A aplicação estará disponível em `http://localhost:5173`.

## Roadmap de Funcionalidades

### Fase 1: Coleta de Dados e API Backend

- [ ] Estrutura básica do projeto (client/server).
- [ ] Backend em Python com FastAPI.
- [ ] Configuração do ambiente virtual e `requirements.txt`.
- [ ] Implementar a conexão com o banco de dados (ex: SQLAlchemy com Alembic para migrações).
- [ ] Script Python para popular a tabela `cryptocurrencies` a partir da CoinGecko (`/coins/markets`).
- [ ] Script Python para popular a tabela `price_history` a partir da CoinGecko (`/coins/{id}/market_chart`), respeitando o rate limiting.
- [ ] Endpoints no FastAPI para expor os dados das criptomoedas e o histórico de preços.

### Fase 2: Dashboard Frontend

- [ ] Frontend em React/TypeScript com Vite e TailwindCSS.
- [ ] Exibir a lista de criptomoedas com preço atual e variação 24h.
- [ ] Página de detalhes para uma criptomoeda com gráfico histórico interativo.

### Fase 3: Armazenamento e Predição

- [ ] Implementar um mecanismo para coletar e armazenar dados diariamente de forma automatizada (ex: cron job).
- [ ] Desenvolver e integrar modelos de predição de série temporal (ex: ARIMA, Prophet, LSTM) usando bibliotecas Python (pandas, scikit-learn, tensorflow/pytorch).
- [ ] Criar endpoints no FastAPI para servir as predições.
- [ ] Exibir as predições no frontend.
