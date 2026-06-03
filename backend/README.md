# Investor OS Backend

FastAPI backend for the Investor OS local dashboard. It connects to Interactive Brokers TWS or IB Gateway through `ibapi`, serves portfolio data, and serves read-only US equity options analysis.

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
```

`Settings.options_database_path` stores the SQLite completed daily-bar cache used by the Options analysis endpoints. The `data/` directory is runtime-local and ignored by git. Completed bars are cached by ticker and trading date; the current trading day is fetched separately and is not finalized into the cache.

## Options API

Phase 2 Options support is read-only and limited to US equity options. It does not include order entry, alerts, watchlists, or non-US option workflows.

```text
GET /options/{ticker}/analysis
GET /options/{ticker}/chain?expiration=YYYY-MM-DD
WS  /options/{ticker}/chain/ws?expiration=YYYY-MM-DD
```

The analysis endpoint returns daily candles, Bollinger Bands, RSI, the latest underlying price, and available expirations. The chain endpoint returns a bounded strike range for one selected expiration.

The chain WebSocket subscribes to IB market data for calls and puts in the active ticker, selected expiration, and bounded strike range. It sends a snapshot followed by row updates as ticks arrive, then cancels those IB market-data subscriptions when the WebSocket disconnects. Quote and Greek availability depends on the user's IB market-data subscriptions and delayed-data settings.

## Verification

Run backend tests:

```sh
uv run pytest
```
