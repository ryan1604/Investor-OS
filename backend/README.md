# Investor OS Backend

FastAPI backend for the Investor OS local dashboard. It connects to Interactive Brokers TWS or IB Gateway through `ibapi`, serves portfolio data, options analysis, options screeners, order entry and order state, manual stock-analysis models, portfolio chart history, and Options Trade Tracker workspaces.

## Local Setup

Install or update dependencies:

```sh
uv sync
```

Start TWS or IB Gateway, then run the API:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Avoid `--reload` while connected to IB unless needed, because reload workers can create extra API sessions with the same client ID.

## Runtime Settings

Runtime settings are fixed local Python defaults in `app/config.py`. They are not loaded from `.env` files or environment variables.

```text
Settings.ib_host = "127.0.0.1"
Settings.ib_port = 7496
Settings.ib_client_id = 1
Settings.options_database_path = "data/options.sqlite3"
Settings.options_screeners_database_path = "data/options_screeners.sqlite3"
Settings.options_trade_trackers_database_path = "data/options_trade_trackers.sqlite3"
Settings.stock_analysis_database_path = "data/stock_analysis.sqlite3"
Settings.portfolio_chart_values_database_path = "data/portfolio_chart_values.sqlite3"
Settings.allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
```

`Settings.options_database_path` stores the SQLite completed daily-bar cache used by the Options analysis endpoints. The `data/` directory is runtime-local and ignored by git. Completed bars are cached by ticker and trading date; the current trading day is fetched separately and is not finalized into the cache.

`Settings.options_screeners_database_path` stores durable CSP/CC and CS ticker lists plus independent saved filters for the CSP, CC, and CS screeners. Scan jobs and completed result snapshots are in-memory only.

`Settings.stock_analysis_database_path` stores saved manual Stock Analysis scenario models. The store keeps bull, base, and bear payloads per ticker in the runtime-local `data/stock_analysis.sqlite3` database.

`Settings.portfolio_chart_values_database_path` stores manual account-scoped Portfolio history by month. Replacing one account's rows is transactional and does not affect other accounts.

`Settings.options_trade_trackers_database_path` stores named trackers, tracker-scoped trade rows and notes, and global strategy options. Trade row identity is scoped by tracker, and startup migrates the legacy global row-id schema when present.

All five local SQLite stores use Python's standard `sqlite3` module directly. The backend does not carry SQLAlchemy or Alembic; local schema initialization and compatibility migrations are handled by the stores.

## Portfolio API

```text
GET /portfolio
GET /portfolio/chart-values?account={account}
PUT /portfolio/chart-values?account={account}
WS  /portfolio/ws
```

The portfolio snapshot returns IB connection status, account summaries, positions, market prices, and P&L values. The WebSocket sends the current snapshot and live updates while the backend remains connected to IB.

Portfolio chart-value endpoints load or transactionally replace manual monthly history for one normalized account.

## Options API

Options support is limited to US equity options analysis and live chain data. Order tickets for stocks and option strategies are submitted through the Orders API.

```text
GET /options/{ticker}/analysis
GET /options/{ticker}/chain?expiration=YYYY-MM-DD
GET /options/{ticker}/expirations
WS  /options/{ticker}/chain/ws?expiration=YYYY-MM-DD
WS  /options/{ticker}/chart/ws
```

The analysis endpoint returns daily candles, Bollinger Bands, RSI, the latest underlying price, and available expirations. The chain endpoint returns a bounded strike range for one selected expiration. The expirations endpoint refreshes available expirations without loading the full analysis payload.

The chain WebSocket subscribes to IB market data for calls and puts in the active ticker, selected expiration, and bounded strike range. It sends a snapshot followed by row updates as ticks arrive, then cancels those IB market-data subscriptions when the WebSocket disconnects. Quote and Greek availability depends on the user's IB market-data subscriptions and delayed-data settings.

The chart WebSocket streams latest chart data for the active ticker.

## Options Screeners API

```text
GET  /options-screeners/settings
PUT  /options-screeners/settings/ticker-lists/{list_name}
PUT  /options-screeners/settings/filters/{screener}
GET  /options-screeners/state
GET  /options-screeners/jobs/{job_id}
GET  /options-screeners/snapshots/{screener}
POST /options-screeners/scans/{screener}
POST /options-screeners/scans/{job_id}/cancel
POST /options-screeners/quotes/refresh
POST /options-screeners/quotes/refresh-spread
WS   /options-screeners/scans/ws
```

CSP and CC share one ticker list; CS has its own. Filters are durable per screener. Scan jobs, progress, completed snapshots, and warnings are retained in memory while the backend process is running. Quote refresh endpoints reprice selected rows before the frontend opens an option-strategy ticket.

## Orders API

```text
GET   /orders
POST  /orders/preview
POST  /orders/transmit
PATCH /orders/{order_id}
POST  /orders/{order_id}/cancel
WS    /orders/ws
```

Order requests require an explicit account. Stock orders support whole-share buy and sell tickets with market or limit order types and DAY or GTC time-in-force. Option strategy orders support one or more signed legs with a required limit price and optional take-profit and stop-loss prices.

`/orders/preview` validates and summarizes a ticket without transmitting it. `/orders/transmit` submits the ticket to IB. Amendments can update editable order prices and time-in-force values, and cancellation requires the submitted account. Order records are reconciled with IB and use IB-authoritative status updates; `/orders/ws` sends snapshots and incremental updates for active orders and current-day terminal history.

## Stock Analysis API

```text
GET  /stock-analysis
POST /stock-analysis/current-prices/refresh
GET /stock-analysis/{ticker}
GET /stock-analysis/{ticker}/current-price
PUT /stock-analysis/{ticker}
```

Stock Analysis stores manual bull, base, and bear scenario models per ticker. First-time tickers return an empty scenario payload. The collection endpoint lists every saved model for Rank Stocks. The refresh endpoint updates saved current-price snapshots best-effort and preserves stale prices when IB lookup fails. The focused current-price endpoint persists a successful snapshot without loading the full Options analysis payload.

## Options Trade Tracker API

```text
GET    /options-trade-trackers
POST   /options-trade-trackers
GET    /options-trade-trackers/strategy-options
PUT    /options-trade-trackers/strategy-options
GET    /options-trade-trackers/{tracker_id}
PATCH  /options-trade-trackers/{tracker_id}
DELETE /options-trade-trackers/{tracker_id}
PUT    /options-trade-trackers/{tracker_id}/trades
PUT    /options-trade-trackers/{tracker_id}/notes
```

Trackers own ordered trade rows and notes. Strategy options are global and survive tracker deletion. Trade replacement is transactional; invalid rows return validation responses without partially replacing saved data.

## Verification

Run backend tests:

```sh
uv run pytest
```
