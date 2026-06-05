# Investor OS Backend

FastAPI backend for the Investor OS local dashboard. It connects to Interactive Brokers TWS or IB Gateway through `ibapi`, serves portfolio data, options analysis, order entry and order state, and manual stock-analysis models.

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
Settings.ib_port = 7497
Settings.ib_client_id = 1
Settings.options_database_path = "data/options.sqlite3"
Settings.stock_analysis_database_path = "data/stock_analysis.sqlite3"
Settings.allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
```

`Settings.options_database_path` stores the SQLite completed daily-bar cache used by the Options analysis endpoints. The `data/` directory is runtime-local and ignored by git. Completed bars are cached by ticker and trading date; the current trading day is fetched separately and is not finalized into the cache.

`Settings.stock_analysis_database_path` stores saved manual Stock Analysis scenario models. The store keeps bull, base, and bear payloads per ticker in the runtime-local `data/stock_analysis.sqlite3` database.

Both local SQLite stores use Python's standard `sqlite3` module directly. The backend does not currently carry SQLAlchemy or Alembic because there is no ORM or migration layer in the supported runtime contract.

## Portfolio API

```text
GET /portfolio
WS  /portfolio/ws
```

The portfolio snapshot returns IB connection status, account summaries, positions, market prices, and P&L values. The WebSocket sends the current snapshot and live updates while the backend remains connected to IB.

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
GET /stock-analysis/{ticker}
GET /stock-analysis/{ticker}/current-price
PUT /stock-analysis/{ticker}
```

Stock Analysis stores manual bull, base, and bear scenario models per ticker. First-time tickers return an empty scenario payload. Saved models are persisted in `Settings.stock_analysis_database_path`, and the current-price endpoint reuses the Options analysis price source.

## Verification

Run backend tests:

```sh
uv run pytest
```
