# Performance Baselines

Task 9.5.1 adds repeatable baseline commands before any optimization work. The
workloads use fake providers and generated fixtures, so they do not require live
Interactive Brokers credentials or a real account.

## Backend

Command:

```powershell
cd backend
uv run python -m scripts.performance_baseline --output ../docs/backend-performance-baseline.json
uv run pytest
```

Default workload:

- 10 HTTP iterations per endpoint.
- 250 generated portfolio positions across stocks and options.
- 120 option-chain strikes with call and put quotes.
- 260 chart points.
- Temporary SQLite database for stock-analysis reads and writes.

Captured metrics:

- HTTP latency and payload sizes for `/portfolio`, `/options/{ticker}/analysis`,
  `/options/{ticker}/chain`, stock-analysis reads/writes, and `/orders`.
- Concurrent HTTP p50, p95, p99, worker count, request count, and status counts
  for options analysis, option chain, stock-analysis current-price,
  stock-analysis reads/writes, order transmit, and order amend workloads.
- Fake-provider wait timings for portfolio status, positions, account summaries,
  options analysis, and option chain snapshots.
- SQLite read/write timings for stock-analysis models.
- WebSocket first-message or update receive timings and payload sizes for
  portfolio, option chain, chart, and orders streams.
- Portfolio subscriber count and queue-depth snapshot after the run.
- Stream guardrails for maximum option-chain stream strikes, bounded order
  subscriber queues, and latest-state portfolio publishing.

Initial backend budgets:

- `/portfolio` p95 <= 75 ms.
- `/options/{ticker}/analysis` p95 <= 125 ms.
- `/options/{ticker}/chain` p95 <= 125 ms.
- Stock-analysis write p95 <= 50 ms.
- WebSocket message p95 <= 75 ms.
- Concurrent fake-provider request p95 <= 250 ms.

Configured backend concurrency guardrails:

- Options analysis and stock-analysis current-price: 2 concurrent requests.
- Option chain: 2 concurrent requests.
- Order transmit, amend, and cancel: 1 concurrent mutation.
- Stock-analysis reads: 4 concurrent requests.
- Stock-analysis writes: 2 concurrent requests.
- Queue wait budget before returning `503`: 250 ms.
- Shared option-chain context executor: 2 workers.

Configured backend stream guardrails:

- Option-chain streams: at most 80 strikes, or 160 IB market-data subscriptions
  across calls and puts.
- Option-chain subscription logs include ticker, expiration, strike count,
  subscription count, open/close time, and per-update duration.
- Chart streams load the completed historical window once per stream and update
  latest Bollinger/RSI values from cached completed history for same-day ticks.
- Portfolio refresh stores one latest snapshot and publishes that snapshot to
  subscribers with one-slot drop-oldest queues.
- Order WebSocket subscribers use bounded queues of 32 updates with a
  drop-oldest/latest-state policy for slow clients.

Initial backend snapshot from
`uv run python -m scripts.performance_baseline --output ../docs/backend-performance-baseline.json`
on June 5, 2026:

| Workload | p95 latency | p95 payload |
| --- | ---: | ---: |
| `/portfolio` | 2.496 ms | 129,786 bytes |
| `/options/{ticker}/analysis` | 1.385 ms | 49,785 bytes |
| `/options/{ticker}/chain` | 3.135 ms | 74,731 bytes |
| Stock-analysis read | 2.479 ms | 89 bytes |
| Stock-analysis write | 7.138 ms | 344 bytes |
| `/orders` snapshot | 0.925 ms | 2 bytes |
| Portfolio WebSocket first message | 0.632 ms | 129,786 bytes |
| Option-chain WebSocket messages | 1.189 ms | 74,738 bytes |
| Chart WebSocket messages | 0.286 ms | 256 bytes |
| Orders WebSocket first message | 0.154 ms | 44 bytes |

Initial concurrent backend snapshot from the same fake-provider baseline:

| Workload | p50 | p95 | p99 | Status counts |
| --- | ---: | ---: | ---: | --- |
| Options analysis | 2.728 ms | 2.956 ms | 2.956 ms | `200: 10` |
| Option chain | 9.007 ms | 10.965 ms | 10.965 ms | `200: 10` |
| Stock-analysis current-price | 2.393 ms | 2.913 ms | 2.913 ms | `200: 10` |
| Stock-analysis read | 3.269 ms | 3.869 ms | 3.869 ms | `200: 10` |
| Stock-analysis write | 12.837 ms | 56.030 ms | 56.030 ms | `200: 10` |
| Order transmit | 3.283 ms | 4.180 ms | 4.180 ms | `200: 10` |
| Order amend | 5.188 ms | 5.715 ms | 5.715 ms | `200: 10` |

Instrumentation highlights from the same run:

- Fake IB position wait p95: 2.165 ms.
- Fake IB option-chain wait p95: 1.990 ms.
- SQLite stock-analysis read/write p95: 1.640 ms / 54.877 ms.
- Portfolio subscriber count after cleanup: 0; queue depths: none.

Cold and warm options-analysis instrumentation is emitted by the backend logger
as `Options historical hydration` events with `cache_state`, `chunks`,
`ib_wait_ms`, `cache_hit_ratio`, and `payload_bytes` fields. Cold loads retain
the 10-year history window and chunk by `MAX_HISTORICAL_CHUNK_DAYS`; warm loads
reuse cached completed bars and only fetch the latest missing range.

## Frontend

Command:

```powershell
cd frontend
pnpm bundle:report
pnpm test
pnpm lint
pnpm build
```

The bundle report writes `docs/frontend-bundle-baseline.json` after a production
build. It records every emitted JS and CSS asset with raw, gzip, and brotli
sizes, plus summaries for initial chunks, all JS, and all CSS.

Initial frontend budgets:

- Initial JS gzip <= 180 KB.
- Total JS gzip <= 320 KB.
- Total CSS gzip <= 60 KB.

Initial frontend snapshot from `pnpm bundle:report` on June 5, 2026:

| Asset group | Raw | gzip | brotli |
| --- | ---: | ---: | ---: |
| Initial assets | 711,147 bytes | 205,609 bytes | 174,573 bytes |
| JavaScript | 628,744 bytes | 191,725 bytes | 162,750 bytes |
| CSS | 82,403 bytes | 13,884 bytes | 11,823 bytes |

The current production build emits one initial JavaScript chunk
(`assets/index-DdXGTJiK.js`) and one initial CSS chunk
(`assets/index-DXrAXMGQ.css`). The initial JS gzip size is above the target
budget, so Task 9.5.4 should start with route-level code splitting and confirm
the bundle report moves the number below budget.

Task 9.5.4 frontend snapshot from `pnpm bundle:report` on June 5, 2026:

| Asset group | Raw | gzip | brotli |
| --- | ---: | ---: | ---: |
| Initial assets | 466,826 bytes | 132,579 bytes | 113,698 bytes |
| Initial JavaScript | 384,423 bytes | 118,695 bytes | 101,875 bytes |
| JavaScript total | 634,699 bytes | 200,582 bytes | 173,692 bytes |
| CSS | 82,403 bytes | 13,884 bytes | 11,823 bytes |

The split production build keeps Portfolio in the initial app shell and moves
inactive pages and heavy options paths into route or on-demand chunks:

- Initial app shell: `assets/index-DlJuzjxo.js`, 118,695 gzip bytes.
- Options route: `assets/OptionsPage-BvE-mpWs.js`, 8,886 gzip bytes.
- Orders route: `assets/OrdersPage-CR-CR5mN.js`, 4,293 gzip bytes.
- Stock Analysis route: `assets/StockAnalysisPage-Bm97yt0D.js`, 4,601 gzip bytes.
- Options chart engine: `assets/chartHelpers-CbkISij6.js`, 53,545 gzip bytes,
  loaded outside the initial Portfolio path.
- Options tickets and chart components are separate non-initial chunks:
  `OptionStrategyTicket`, `StockTradeTicket`, `OptionsChart`, and `RsiChart`.

Task 9.5.5 option-chain render profile from:

```powershell
cd frontend
$env:VITE_PRINT_OPTION_CHAIN_PROFILE='1'
pnpm exec vitest run src/performance/optionChainProfile.test.tsx --disableConsoleIntercept --reporter verbose
```

The profile uses React Profiler around `OptionChainTable`, applies a batched
set of live row updates with `mergeLiveChainRows`, and treats updates over
16.7 ms as dropped-frame risk.

| Strikes | Updates/sec | Commit duration | Dropped-frame risk |
| ---: | ---: | ---: | --- |
| 25 | 1 | 10.798 ms | No |
| 25 | 5 | 22.276 ms | Yes |
| 25 | 10 | 9.063 ms | No |
| 100 | 1 | 14.433 ms | No |
| 100 | 5 | 14.990 ms | No |
| 100 | 10 | 17.455 ms | Yes |
| 250 | 1 | 130.828 ms | Yes |
| 250 | 5 | 35.931 ms | Yes |
| 250 | 10 | 41.080 ms | Yes |

Task 9.5.5 keeps option-chain WebSocket row updates pending until the next
animation frame, merges each frame with one strike-index map, memoizes display
row construction, and memoizes quote cells so unchanged quote objects can skip
cell rerenders. It also moves portfolio and order live subscriptions into route
components so inactive pages do not rerender from unrelated streams. Chart
stream state now stores the latest update and live underlying price instead of
allocating replacement candle, Bollinger, and RSI arrays on every tick; chart
series still receive live paints from `latestUpdate`.

The 250-strike profile remains above a single-frame budget in jsdom and should
be treated as the documented threshold for a future virtualization pass. Current
backend option-chain stream guardrails cap live subscriptions below that scale,
so the measured frontend budget is acceptable for the current guarded workload
while still leaving a clear escalation point.

Task 9.5.6 request-abort profile from focused frontend tests:

| Scenario | Before | After | Coverage |
| --- | ---: | ---: | --- |
| Options analysis route unmount while analysis is in flight | 1 in-flight, 0 aborted | 1 in-flight, 1 aborted | `useOptionsAnalysis.test.ts` |
| Option-chain route cleanup while chain fetch is in flight | 1 in-flight, 0 aborted | 1 in-flight, 1 aborted | `useOptionChain.test.ts` |
| Stock Analysis route unmount while model and current-price loads are in flight | 2 in-flight, 0 aborted | 2 in-flight, 2 aborted | `StockAnalysisPage.test.tsx` |
| Stock Analysis edit supersedes an in-flight autosave | 1 in-flight, 0 aborted | 1 in-flight, 1 aborted | `StockAnalysisPage.test.tsx` |

Options ticker search still disables the search control while loading, so Task
9.5.6 does not add rapid overlapping Options searches. Options request aborts
are scoped to cleanup, unmount, navigation away from the lazy route, or another
real submit if the UI later allows one.

Task 9.5.6 CSS and asset snapshot from `pnpm bundle:report` on June 5, 2026:

| Asset group | Raw | gzip | brotli |
| --- | ---: | ---: | ---: |
| Initial assets | 467,139 bytes | 132,656 bytes | 113,727 bytes |
| JavaScript total | 635,986 bytes | 200,954 bytes | 173,987 bytes |
| CSS | 82,403 bytes | 13,884 bytes | 11,823 bytes |
| Geist font files | 76,420 bytes | n/a | n/a |

The production HTML keeps the single CSS file render-blocking:
`assets/index-DXrAXMGQ.css`. The emitted Geist font files are:
`geist-latin-wght-normal-BgDaEnEv.woff2` at 29,400 bytes,
`geist-latin-ext-wght-normal-DC-KSUi6.woff2` at 16,512 bytes,
`geist-cyrillic-wght-normal-BEAKL7Jp.woff2` at 15,084 bytes,
`geist-vietnamese-wght-normal-6IgcOCM7.woff2` at 8,004 bytes, and
`geist-cyrillic-ext-wght-normal-DjL33-gN.woff2` at 7,420 bytes.

Chrome Coverage and Lighthouse were not available in the project-local toolchain
(`pnpm exec playwright --version` and `pnpm exec lighthouse --version` both
failed with command-not-found), so unused CSS and render-blocking timing were
not captured from a live browser in this pass. Bundle output and code search
did not justify pruning:

- `tw-animate-css` backs `animate-in`, `fade-in`, `zoom-in`, `slide-in`, and
  related Radix state classes in shared UI primitives.
- `@fontsource-variable/geist` is imported by `index.css` and provides the
  configured `--font-sans`.
- `shadcn/tailwind.css`, `radix-ui`, `class-variance-authority`, `clsx`,
  `tailwind-merge`, `sonner`, `lucide-react`, and `lightweight-charts` all have
  source references in active app code.
- No source-level asset imports exist; public assets are `favicon.svg` at
  9,522 bytes and `icons.svg` at 5,031 bytes.

Representative profiling fixtures live in
`frontend/src/performance/fixtures.ts`:

- Portfolio load: 250 generated stock and option positions.
- Options ticker search and chart state: 260 chart stream updates.
- Option-chain streaming: 120 initial rows plus configurable live row updates.
- Global portfolio stream: configurable portfolio snapshots with price changes.
- Global order stream: configurable order status updates.

Use these fixtures in React profiler sessions, render-count tests, or future
large-fixture regression tests so later optimization tasks compare the same
payload shapes.
