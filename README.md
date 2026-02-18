# TentacleLab & Prediction

Este projeto é um dashboard para visualização de dados de criptomoedas em tempo real, com um roadmap que inclui a implementação de modelos de Machine Learning para predição de valores.

## Arquitetura Técnica

O projeto será desenvolvido utilizando uma arquitetura de monorepo, separando o `client` (frontend) do `server` (backend).

### Frontend (Client)

- **Framework:** React com TypeScript
- **Build Tool:** Vite
- **Estilização:** TailwindCSS
- **Gráficos:** Chart.js ou uma biblioteca similar

### Backend (Server)

- **Linguagem:** Python
- **Framework:** FastAPI
- **Banco de Dados:** PostgreSQL (recomendado) ou SQLite para desenvolvimento local.
- **Comunicação com API:** `coingecko-sdk`

## Como Começar (Setup)

### 1. Pré-requisitos

- Node.js (v18+) e `npm` ou `yarn`
- Python (v3.9+) e `pip`
- Git

### 2. Configuração do Ambiente

1.  **Clone o repositório:**
    ```bash
    git clone <URL_DO_REPOSITORIO>
    cd crypto_dashboard
    ```

2.  **Configure o Backend (Python):**
    - Crie e ative um ambiente virtual na raiz do projeto:
      ```bash
      python -m venv server/venv
      source server/venv/bin/activate  # No Windows: server\venv\Scripts\activate
      ```
    - Instale as dependências de produção e desenvolvimento:
      ```bash
      pip install -r server/requirements.txt
      pip install -r server/requirements-dev.txt
      ```
    - Crie o arquivo de variáveis de ambiente a partir do exemplo e configure-o:
      ```bash
      cp server/.env.example server/.env
      # Agora, edite o arquivo server/.env com a URL do seu banco de dados
      ```
      *Por padrão, o projeto usará um banco de dados SQLite local, que não exige configuração. Para usar PostgreSQL, ajuste a variável `DATABASE_URL`.*

3.  **Configure o Frontend (React):**
    - Navegue até a pasta `client` e instale as dependências:
      ```bash
      cd client
      npm install
      cd .. 
      ```

## Desenvolvimento

### Rodando o Servidor da API (Backend)

- Com o ambiente virtual ativado (`source server/venv/bin/activate`), inicie o servidor FastAPI a partir da raiz do projeto:
  ```bash
  uvicorn src.main:app --reload --app-dir server
  ```
- A API estará disponível em `http://localhost:8000` e a documentação interativa em `http://localhost:8000/docs`.

### Rodando a Aplicação Web (Frontend)

- Em um novo terminal, inicie o servidor de desenvolvimento do React:
  ```bash
  npm run dev --prefix client
  ```
- A aplicação web estará disponível em `http://localhost:5173`.

## Testes e Scripts

### Migracoes de Banco (Alembic)

- O backend usa Alembic para versionar mudancas de schema.
- Para aplicar as migracoes a partir da pasta server, execute: alembic upgrade head
- Esta revisao altera as colunas price_history.market_cap_usd e price_history.total_volume_usd para DECIMAL(30, 10).

### Rodando os Testes Unitários

- O projeto usa `pytest` para testes unitários. Os testes são projetados para rodar de forma isolada (com mocks), sem depender da API externa ou de um banco de dados real.
- Para rodar os testes, execute o seguinte comando a partir da raiz do projeto (com o venv ativado):
  ```bash
  python -m pytest server/src/tests/
  ```

### Rodando o Script de Coleta de Dados

- O script `populate_db.py` é responsável por criar as tabelas no banco de dados e popular com os dados mais recentes da CoinGecko.
- **Atenção:** Antes de rodar, certifique-se que seu arquivo `server/.env` está configurado corretamente.

- Para executar o script, rode um dos seguintes comandos a partir da raiz do projeto (com o venv ativado):
  ```bash
  # Opção 1: Executar como módulo Python
  python -m server.src.scripts.populate_db
  
  # Opção 2: Executar o script diretamente
  python server/src/scripts/populate_db.py
  ```
- **Nota:** Este processo pode levar vários minutos, pois ele busca o histórico de centenas de moedas e faz pausas para respeitar o limite de chamadas da API.

## Modelo de Dados (Banco de Dados)
*(Seções de Modelo de Dados e APIs permanecem as mesmas)...*
...
(O resto do conteúdo do README continua aqui)









