# Investor OS Frontend

React and Vite frontend for the Investor OS Portfolio and read-only Options dashboard.

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

## Options View

The Options page supports read-only US equity option analysis. It does not place orders, manage alerts, maintain watchlists, or support non-US option workflows.

After a ticker search, the page loads analysis data from:

```text
GET /options/{ticker}/analysis
```

The selected expiration chain is loaded from:

```text
GET /options/{ticker}/chain?expiration=YYYY-MM-DD
```

While the selected expiration is visible, the page opens one live chain stream:

```text
WS /options/{ticker}/chain/ws?expiration=YYYY-MM-DD
```

Changing ticker or expiration closes the previous stream and opens a new one. Leaving the Options page closes the stream. Quote and Greek fields depend on the user's Interactive Brokers market-data subscriptions and delayed-data settings.
