# Investor OS Frontend

React and Vite frontend for the Investor OS local dashboard. It includes Portfolio, Options, Orders, and Stock Analysis workflows backed by the FastAPI service.

## Local Setup

Install dependencies:

```sh
pnpm install
```

Start the development server:

```sh
pnpm dev
```

Create a production build:

```sh
pnpm build
```

Run lint checks:

```sh
pnpm lint
```

## Backend Connection

The dashboard reads from the backend API configured by `VITE_API_BASE_URL`.

```sh
VITE_API_BASE_URL=http://127.0.0.1:8000
```

If the variable is not set, the app uses `http://127.0.0.1:8000`.

On load, the Portfolio page fetches the current snapshot from:

```text
GET /portfolio
```

It also opens a live stream for portfolio updates at:

```text
WS /portfolio/ws
```

The WebSocket URL is derived from `VITE_API_BASE_URL`, replacing `http` with
`ws` or `https` with `wss`.

## Portfolio View

The Portfolio page shows IB connection status, account summaries, positions, market prices, and P&L values. Account selection is explicit and is shared with order tickets that need an account.

## Options View

The Options page supports US equity option analysis, live chains, chart overlays, stock order tickets, and option strategy tickets.

After a ticker search, the page loads analysis data from:

```text
GET /options/{ticker}/analysis
```

The selected expiration chain is loaded from:

```text
GET /options/{ticker}/chain?expiration=YYYY-MM-DD
```

Available expirations can be refreshed from:

```text
GET /options/{ticker}/expirations
```

While the selected expiration is visible, the page opens one live chain stream:

```text
WS /options/{ticker}/chain/ws?expiration=YYYY-MM-DD
```

The chart also opens a live ticker stream:

```text
WS /options/{ticker}/chart/ws
```

Changing ticker or expiration closes the previous stream and opens a new one. Leaving the Options page closes the streams. Quote and Greek fields depend on the user's Interactive Brokers market-data subscriptions and delayed-data settings.

The stock ticket supports explicit account selection, whole-share quantities, buy and sell actions, market or limit orders, and DAY or GTC time-in-force. The option strategy ticket supports signed option legs, required strategy limit prices, optional take-profit and stop-loss prices, order previews, and transmitted orders.

## Orders View

The Orders page shows active IB orders separately from current-day terminal history. It reads the initial snapshot from:

```text
GET /orders
```

Order state stays live through:

```text
WS /orders/ws
```

The order WebSocket is intentionally owned by the app shell rather than only the
Orders page so Options chart overlays and the Orders page share the same fresh
order state.

Order tickets and controls call:

```text
POST  /orders/preview
POST  /orders/transmit
PATCH /orders/{order_id}
POST  /orders/{order_id}/cancel
```

Order status is reconciled from IB. Editable orders can be amended, and active orders can be cancelled with the submitted account.

## Stock Analysis View

The Stock Analysis page is a manual valuation workspace with bull, base, and bear scenario tables. It loads saved ticker models from:

```text
GET /stock-analysis/{ticker}
```

It can fetch the latest available current price from:

```text
GET /stock-analysis/{ticker}/current-price
```

Scenario edits autosave to:

```text
PUT /stock-analysis/{ticker}
```

Searching a saved ticker restores its scenarios. Searching a first-time ticker starts from empty scenario inputs.
