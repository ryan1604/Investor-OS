# Investor OS Frontend

React and Vite frontend for the Investor OS local dashboard. It includes Portfolio, Portfolio Analysis, Options, CSP/CC/CS screeners, Options Trade Tracker, Orders, Stock Analysis, Earnings Watch, and Rank Stocks workflows backed by the FastAPI service.

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

## Application Loading

`src/lib/pages.ts` defines the sidebar order, labels, icons, and `AppPage` IDs; `src/App.tsx` uses those IDs for its typed page lookup and eagerly imports page modules into the current production bundle. Portfolio is the default page. Most pages mount only while active; Options mounts on its first visit and then stays mounted but hidden when another page is selected, retaining its workspace while pausing its chain and chart streams. App owns the shared Portfolio state and one Orders subscription used by both Options and Orders.

The Portfolio Refresh action fetches the current snapshot from:

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

Monthly Amount invested history is loaded and replaced through:

```text
GET /portfolio/chart-values?account={account}
PUT /portfolio/chart-values?account={account}
```

Net account value displays saved daily NAV with date ranges, tooltips, and sync status. 3Y/5Y appear when history covers them. Amount/Percentage toggles between NAV and change from the selected range's first value, including cash flows. The chart polls every 30 seconds, separates currency periods, and supports saved accounts while TWS is offline. Monthly Amount invested has its own chart and editor. Account switches isolate data and drafts.

## Portfolio Analysis View

The Portfolio Analysis page shows the selected account's market risk from `/portfolio/analysis/ws`: summary cards, a coverage banner, an exposure table grouped by underlying and strategy, the stress grid with the estimated distance to margin call, Realised Risk cards, and Risk History charts. It is read-only.

Risk limits and beta overrides are edited on the page. Limits are saved per account and colour the limited metrics green, amber, or red; nothing is banded until limits are saved. Risk History loads `/portfolio/analysis/history` every minute, keeps missed sessions as gaps, and marks intraday snapshots.

Leaving the page closes the WebSocket, which releases the extra market-data feeds.

## Options View

The Options page supports US equity option analysis, live chains, chart overlays, stock order tickets, and option strategy tickets.

After a ticker search, the page loads analysis data from:

```text
GET /options/{ticker}/analysis
```

The backend also exposes a REST chain snapshot:

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

The visible chain initializes from this WebSocket's snapshot; the frontend does not automatically call the REST chain endpoint.

The chart also opens a live ticker stream:

```text
WS /options/{ticker}/chart/ws
```

Changing ticker or expiration closes the previous stream and opens a new one. Leaving the Options page closes the streams. Quote and Greek fields depend on the user's Interactive Brokers market-data subscriptions and delayed-data settings.

The stock ticket supports explicit account selection, whole-share quantities, buy and sell actions, market or limit orders, and DAY or GTC time-in-force. The option strategy ticket supports signed option legs, required strategy limit prices, optional take-profit and stop-loss prices, order previews, and transmitted orders.

## Options Screener Views

CSP, CC, and CS screeners share one provider for durable settings, active jobs, completed snapshots, live progress, warnings, table sorting, and quote refresh before ticket opening.

`useOptionsScreeners` exposes a typed `screeners` record with `csp`, `cc`, and `cs` slices. Each slice keeps its filter draft, confirmed filters, validation/save status, sort, tickers, and scan actions. The shared filter hook retains the 350 ms autosave debounce; the provider retains the initial REST load and one scan WebSocket while pages change.

```text
GET  /options-screeners/settings
PUT  /options-screeners/settings/ticker-lists/{list_name}
PUT  /options-screeners/settings/filters/{screener}
GET  /options-screeners/state
POST /options-screeners/scans/{screener}
POST /options-screeners/scans/{job_id}/cancel
POST /options-screeners/quotes/refresh
POST /options-screeners/quotes/refresh-spread
WS   /options-screeners/scans/ws
```

The three pages use a shared screener shell and scan/cancel button, retaining their existing alerts, refresh notices, and screener-specific controls. Screener result and contract types live in `src/api/optionsScreeners.ts`. CSP and CC share a ticker list and single-leg result table patterns. CS has its own ticker list, spread filters, spread table columns, and two-leg ticket mapping. All three open the shared option-strategy ticket only after refreshing the selected row.

## Orders View

The Orders page shows active IB orders separately from current-day terminal history. It reads the initial snapshot from:

```text
GET /orders
```

Order state stays live through:

```text
WS /orders/ws
```

App opens one order WebSocket when Orders is active or Options has been visited. Before the first Options visit, leaving Orders closes it. After Options has been visited, the connection stays open across page changes to keep its retained workspace current; Options and Orders share the same order state.

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
DELETE /stock-analysis/{ticker}
```

Searching a saved ticker restores its scenarios. Confirmed deletion removes the active saved model and clears the workspace.

## Earnings Watch View

Earnings Watch maintains a ticker list, earnings-date snapshots, and review state.

```text
GET    /earnings-watch
POST   /earnings-watch/tickers
DELETE /earnings-watch/tickers/{ticker}
PUT    /earnings-watch/tickers/{ticker}/reviewed
POST   /earnings-watch/reviews/clear
```

The initial load can start a due backend refresh; the page polls only while that refresh is active.

## Rank Stocks View

Rank Stocks loads all saved Stock Analysis models, displays saved rankings immediately, and refreshes current-price snapshots on open and every 15 minutes.

```text
GET  /stock-analysis
POST /stock-analysis/current-prices/refresh
```

Rankings reuse the Stock Analysis valuation formulas across bull, base, and bear scenarios and five valuation methods. Missing or incomplete values render as `-` and sort last.

## Options Trade Tracker View

Options Trade Tracker manages named workspaces with tracker-scoped trades and notes plus global strategy options.

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

Trades and notes save independently so one response cannot discard unrelated drafts. Tracker loads and mutations are guarded against stale responses. Completed valid trades drive row P&L, totals, stats, monthly charts, and strategy execution data through one shared projection.

Shared account selection, the strategy ticket used by Options and screeners, and presentational ticket form parts live in `src/components/`. Order review/transmit state stays in `features/orders/hooks/useOrderTicketFlow.ts`; features may share hooks and pure helpers, while components shared across features live in `src/components/`.

Shared error fallbacks, local/New York dates, draft number text, and local row IDs live in `src/lib/`. Number formatters in `src/lib/format.ts` cache Intl instances by their options, retaining Portfolio compact notation and the tracker's lowercase `k` labels. `src/components/EditableTableCells.tsx` shares numeric inputs and validation messages while preserving each tracker's formatting and layout.

## Feature Structure

Orders composes `components/OrderSection.tsx` with grouping helpers in `lib/orderGroups.ts`. Rank Stocks builds all scenario/metric rankings in `lib/rankings.ts`, calculating valuation once per saved model. Day Trading separates month loading and saves into `hooks/useDayTradingMonth.ts` and its editable rows into `components/DayTradeTable.tsx`. Earnings Watch keeps refresh effects and mutations in `hooks/useEarningsWatch.ts`; its page retains the current-sort focus behavior. The Options Trade Tracker hook composes separate request coordination and draft-state hooks, retaining request cancellation and independent trade/notes revisions.

```text
src/features/
├── day-trading-tracker/    Calendar-based daily trade rows and save workflow
├── earnings-watch/         Earnings calendar watchlist, review state, and refresh workflow
├── options/                Options analysis, live chain/chart state, and tickets
├── options-screeners/      CSP, CC, and CS scan pages, settings, live jobs, and result tables
├── options-trade-tracker/  Page root with components/, hooks/, and lib/ modules
├── orders/                 Active and terminal IB order management
├── portfolio/              Live portfolio, daily NAV, and monthly invested amounts
├── portfolio-analysis/     Read-only risk dashboard, limits, and risk history
├── rank-stocks/            Rankings over saved Stock Analysis models
└── stock-analysis/         Valuation models, scenarios, autosave, and price lookup
```
