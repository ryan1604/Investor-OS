# Investor OS Backend

FastAPI backend for the Investor OS local dashboard. It connects to Interactive Brokers TWS through `ibapi` and serves portfolio, portfolio analysis, options, screeners, orders, stock analysis, portfolio history, trade trackers, and Earnings Watch.

## Local Setup

Install or update dependencies:

```sh
uv sync
```

Start TWS, then run the API:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Avoid `--reload` while connected to IB unless needed, because reload workers can create extra API sessions with the same client ID.

## Runtime Settings

Runtime settings are fixed local Python defaults in `app/config.py`; Alpha Vantage and IBKR Flex credentials are read from `.env` or `../.env` relative to the working directory. For each key, the first matching entry wins, including an explicitly blank entry. Shell environment variables are not used by this loader. Restart the backend after changing these cached settings.

```text
Settings.ib_host = "127.0.0.1"
Settings.ib_port = 7496
Settings.ib_client_id = 0
Settings.options_database_path = "data/options.sqlite3"
Settings.options_screeners_database_path = "data/options_screeners.sqlite3"
Settings.options_trade_trackers_database_path = "data/options_trade_trackers.sqlite3"
Settings.orders_database_path = "data/orders.sqlite3"
Settings.stock_analysis_database_path = "data/stock_analysis.sqlite3"
Settings.portfolio_chart_values_database_path = "data/portfolio_chart_values.sqlite3"
Settings.earnings_watch_database_path = "data/earnings_watch.sqlite3"
Settings.portfolio_analysis_database_path = "data/portfolio_analysis.sqlite3"
Settings.risk_free_rate = 0.04
Settings.alpha_vantage_api_key = ALPHA_VANTAGE_API_KEY from .env
Settings.ibkr_flex_token = IBKR_FLEX_TOKEN from .env (secret, excluded from settings serialization)
Settings.ibkr_flex_query_id = IBKR_FLEX_QUERY_ID from .env
Settings.allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
```

`Settings.options_database_path` stores the SQLite completed daily-bar cache used by the Options analysis endpoints. The `data/` directory is runtime-local and ignored by git. Completed bars are cached by ticker and trading date; the current trading day is fetched separately and is not finalized into the cache.

`Settings.options_screeners_database_path` stores durable CSP/CC and CS ticker lists plus independent saved filters for the CSP, CC, and CS screeners. Scan jobs and completed result snapshots are in-memory only.

`Settings.stock_analysis_database_path` stores saved manual Stock Analysis scenario models. The store keeps bull, base, and bear payloads per ticker in the runtime-local `data/stock_analysis.sqlite3` database.

`Settings.portfolio_chart_values_database_path` stores manual account-scoped Portfolio history by month. Replacing one account's rows is transactional and does not affect other accounts.

`Settings.options_trade_trackers_database_path` stores named trackers, tracker-scoped trade rows and notes, and global strategy options. Trade row identity is scoped by tracker.

`Settings.orders_database_path` stores local order previews and reconciled order records.

`Settings.earnings_watch_database_path` stores Earnings Watch tickers, review flags, and refresh state.

`Settings.portfolio_analysis_database_path` stores per-session beta cache rows, beta overrides, per-account risk limits, and daily risk snapshots. `Settings.risk_free_rate` is the fixed rate used by the Portfolio Analysis Black-Scholes model.

All seven local SQLite stores use Python's standard `sqlite3` module directly. The backend does not carry SQLAlchemy or Alembic; local schema initialization is handled by the stores.

## Portfolio API

### IBKR Flex setup

Enable Flex Web Service in Client Portal. Configure an Activity Flex query for all tracked accounts with daily breakout, NAV Summary in Base (Account ID, Report Date, Total), and Account Information (Account ID, Currency).

Add credentials to the backend or repository-root `.env`, then restart:

```dotenv
IBKR_FLEX_TOKEN=your-flex-web-service-token
IBKR_FLEX_QUERY_ID=your-activity-query-id
```

Both values are required. Missing credentials disable automatic updates; saved history remains accessible. Tokens and raw request errors are excluded from logs and API responses.

### Current endpoints

```text
GET /portfolio
GET /portfolio/nav?account={account}
GET /portfolio/nav/accounts
GET /portfolio/chart-values?account={account}
PUT /portfolio/chart-values?account={account}
WS  /portfolio/ws
```

The portfolio snapshot returns IB connection status, account summaries, positions, market prices, and P&L values. The WebSocket sends the current snapshot and live updates while the backend remains connected to IB.

Monthly chart endpoints store Amount invested per account. Startup migration removes legacy manual NAV fields while preserving invested amounts and metadata.

Daily NAV uses exact decimal strings keyed by account and report date. Responses include currency and sync status; saved-account discovery works without TWS. Validated imports are transactional, reject currency conflicts, and give Flex precedence over PortfolioAnalyst. No historical-import endpoint or tool is installed.

Flex sync runs at startup and hourly, independently of TWS. It seeds the latest report on an empty store, then recovers missed dates in bounded 30-day ranges with a seven-day correction overlap. Reports must include all saved accounts. Failures preserve history and retry next hour.

Closing reports can lag market close. Status reflects the latest report date: `unconfigured`, `pending`, `syncing`, `failed`, `current`, or `stale`. Missing dates are not filled. Requests have bounded retries and timeouts; shutdown cancels pending work.

## IB Status API

```text
GET /ib/status
GET /ib/market-data-lines
```

`/ib/status` returns the IB connection details. `/ib/market-data-lines` reports the shared market-data line budget: `capacity`, `used`, and per-group `used_by_group` and `pending_by_group` for the portfolio, chart, chain, quote-refresh, and screener groups. It only reads the budget and sends nothing to IB.

## Portfolio Analysis API

```text
GET    /portfolio/analysis?account={account}
WS     /portfolio/analysis/ws?account={account}
GET    /portfolio/analysis/history?account={account}
GET    /portfolio/analysis/beta-overrides
PUT    /portfolio/analysis/beta-overrides/{ticker}
DELETE /portfolio/analysis/beta-overrides/{ticker}
GET    /portfolio/analysis/limits/{account}
PUT    /portfolio/analysis/limits/{account}
```

Analysis is read-only and built from the cached portfolio snapshot. It returns exposure, strategy groups, coverage counts, the stress grid with the Reg T margin estimate, and NAV-based realised statistics. The WebSocket streams one analysis per portfolio refresh and accepts `{"account": "<id>"}` to switch accounts.

Each WebSocket connection registers an analysis viewer. While one exists, position quotes stay subscribed and the stocks underlying option positions that are not held are quoted in the portfolio market-data line group; they are released when the last viewer disconnects.

Beta is a one-year daily regression against SPY, cached per ticker per US session; overrides (`{"beta": x}`, |x| <= 10) take precedence. Limits are replaced as a whole set (`{"limits": {...}}`; an empty object clears them). A risk snapshot is saved at most once a minute while a viewer has been connected for at least a minute; `post_close` snapshots replace `intraday` ones for the same session.

## Options API

Options support is limited to US equity options analysis and live chain data. Order tickets for stocks and option strategies are submitted through the Orders API.

```text
GET /options/{ticker}/analysis
GET /options/{ticker}/chain?expiration=YYYY-MM-DD
GET /options/{ticker}/expirations
WS  /options/{ticker}/chain/ws?expiration=YYYY-MM-DD
WS  /options/{ticker}/chart/ws
```

The analysis endpoint returns daily candles, Bollinger Bands, RSI, the latest underlying price, and available expirations. The chain endpoint resolves all positive metadata strikes for one selected expiration, then returns the delta-filtered rows. The expirations endpoint refreshes available expirations without loading the full analysis payload.

The chain WebSocket resolves the same selected-expiration strikes, applies the configured live-strike cap, and subscribes to IB market data for calls and puts. It sends a snapshot followed by row updates as ticks arrive, then cancels those IB market-data subscriptions when the WebSocket disconnects. Quote and Greek availability depends on the user's IB market-data subscriptions and delayed-data settings.

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
POST  /orders/reconcile
POST  /orders/preview
POST  /orders/transmit
PATCH /orders/{order_id}
POST  /orders/{order_id}/cancel
WS    /orders/ws
```

Order requests require an explicit account. Stock orders support whole-share buy and sell tickets with market or limit order types and DAY or GTC time-in-force. Option strategy orders support one or more signed legs with a required limit price and optional take-profit and stop-loss prices.

`/orders/preview` validates without transmitting, `/orders/transmit` submits to IB, and `/orders/reconcile` requests an IB open-order refresh. Amendments update supported active orders, and `/orders/ws` streams active and current-day terminal state.

External IBKR orders are discovered through the API open-order feed. The backend connects with client ID `0`, enables automatic binding for manual TWS orders, and requests all open orders after connecting. TWS must allow API writes, and read-only API mode must be disabled before externally created orders can be edited. Some orders may be visible without being bindable by this session; those orders stay visible but read-only. Binding manual orders can assign or change API order IDs, so IB permanent IDs are treated as the durable identity when available. Only reconstructed stock market/limit orders, single-option limit orders, and fully described supported option combo limit orders are marked editable; other IB order types remain read-only.

## Stock Analysis API

```text
GET  /stock-analysis
POST /stock-analysis/current-prices/refresh
GET /stock-analysis/{ticker}
GET /stock-analysis/{ticker}/current-price
PUT /stock-analysis/{ticker}
DELETE /stock-analysis/{ticker}
```

Stock Analysis stores manual bull, base, and bear scenario models per ticker. Price refreshes preserve stale values on lookup failure. Deletion idempotently removes the saved model and current-price snapshot.

## Earnings Watch API

```text
GET    /earnings-watch
POST   /earnings-watch/tickers
DELETE /earnings-watch/tickers/{ticker}
PUT    /earnings-watch/tickers/{ticker}/reviewed
POST   /earnings-watch/reviews/clear
```

Earnings Watch persists tickers, review state, last-known dates, and refresh metadata. Loading starts a due provider refresh in the background.

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
