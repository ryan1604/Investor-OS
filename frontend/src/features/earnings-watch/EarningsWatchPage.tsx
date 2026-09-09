import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, Plus, X } from 'lucide-react'

import {
  addEarningsWatchTickers,
  clearEarningsWatchReviews,
  fetchEarningsWatch,
  removeEarningsWatchTicker,
  setEarningsWatchReviewed,
  type EarningsWatchRefreshState,
  type EarningsWatchRow,
} from '@/api/earningsWatch'
import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatEarningsDate,
  millisecondsUntil,
  millisecondsUntilNextNewYorkMidnight,
  nextSort,
  refreshMessage,
  safeErrorMessage,
  sortEarningsWatchRows,
  statusLabel,
  type EarningsWatchSort,
  type EarningsWatchSortKey,
} from '@/features/earnings-watch/lib/earningsWatch'
import { cn } from '@/lib/utils'

const defaultRefresh: EarningsWatchRefreshState = {
  state: 'never_attempted',
  last_attempt_at: null,
  last_success_at: null,
  last_success_date: null,
  error_category: null,
  next_eligible_retry_at: null,
}

const tickerTokenSeparator = /[,\s]+/
const tickerPattern = /^[A-Z0-9.-]+$/

export function EarningsWatchPage() {
  const [rows, setRows] = useState<EarningsWatchRow[]>([])
  const [refresh, setRefresh] = useState<EarningsWatchRefreshState>(defaultRefresh)
  const [tickerInput, setTickerInput] = useState('')
  const [rejectedTokens, setRejectedTokens] = useState<string[]>([])
  const [warning, setWarning] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isAdding, setIsAdding] = useState(false)
  const [isClearing, setIsClearing] = useState(false)
  const [removingTicker, setRemovingTicker] = useState<string | null>(null)
  const [pendingReviewed, setPendingReviewed] = useState<Record<string, boolean>>({})
  const [focusedReviewedTicker, setFocusedReviewedTicker] = useState<string | null>(
    null,
  )
  const [deferredReviewedRows, setDeferredReviewedRows] = useState<
    EarningsWatchRow[] | null
  >(null)
  const [sort, setSort] = useState<EarningsWatchSort>({
    key: 'earnings_date',
    direction: 'asc',
  })
  const rowsRef = useRef(rows)
  const sortRef = useRef(sort)
  const pendingReviewedRef = useRef(pendingReviewed)
  const pollingFailures = useRef(0)
  const tickerInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    rowsRef.current = rows
  }, [rows])

  useEffect(() => {
    sortRef.current = sort
  }, [sort])

  useEffect(() => {
    pendingReviewedRef.current = pendingReviewed
  }, [pendingReviewed])

  const loadState = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) {
      setIsLoading(true)
    }
    try {
      const response = await fetchEarningsWatch()
      setRows(
        mergeRowsPreservingPendingReviews(response.rows, pendingReviewedRef.current),
      )
      setRefresh(response.refresh)
      setWarning(null)
      pollingFailures.current = 0
    } catch (error) {
      setWarning(errorMessage(error, 'Earnings Watch failed.'))
    } finally {
      if (!quiet) {
        setIsLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void loadState()
    }, 0)
    return () => window.clearTimeout(timeout)
  }, [loadState])

  useEffect(() => {
    if (refresh.state !== 'refreshing') {
      return
    }
    const interval = window.setInterval(() => {
      fetchEarningsWatch()
        .then((response) => {
          setRows(
            mergeRowsPreservingPendingReviews(
              response.rows,
              pendingReviewedRef.current,
            ),
          )
          setRefresh(response.refresh)
          pollingFailures.current = 0
          setWarning(null)
        })
        .catch((error) => {
          pollingFailures.current += 1
          if (pollingFailures.current >= 3) {
            setWarning(errorMessage(error, 'Stopped polling earnings dates.'))
            setRefresh((current) => ({ ...current, state: 'failed' }))
          }
        })
    }, 2000)
    return () => window.clearInterval(interval)
  }, [refresh.state])

  useEffect(() => {
    if (refresh.state !== 'cooldown' || !refresh.next_eligible_retry_at) {
      return
    }
    const timeout = window.setTimeout(() => {
      void loadState({ quiet: true })
    }, millisecondsUntil(refresh.next_eligible_retry_at))
    return () => window.clearTimeout(timeout)
  }, [loadState, refresh.next_eligible_retry_at, refresh.state])

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void loadState({ quiet: true })
    }, millisecondsUntilNextNewYorkMidnight())
    return () => window.clearTimeout(timeout)
  }, [loadState])

  const sortedRows = useMemo(
    () => sortEarningsWatchRows(rows, sort),
    [rows, sort],
  )
  const displayRows =
    sort.key === 'reviewed' && focusedReviewedTicker && deferredReviewedRows
      ? deferredReviewedRows
      : sortedRows
  const hasReviewedRows = rows.some((row) => row.reviewed)
  const parsedInput = parseTickerInput(tickerInput)

  async function handleAddTickers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isAdding || parsedInput.valid.length === 0) {
      setRejectedTokens(parsedInput.rejected)
      return
    }

    const previousRows = rowsRef.current
    const now = new Date().toISOString()
    const existing = new Set(previousRows.map((row) => row.ticker))
    const optimisticRows = [
      ...previousRows,
      ...parsedInput.valid
        .filter((ticker) => !existing.has(ticker))
        .map((ticker) => emptyRow(ticker, now)),
    ]
    setRows(optimisticRows)
    setRejectedTokens(parsedInput.rejected)
    setIsAdding(true)
    try {
      const response = await addEarningsWatchTickers(tickerInput)
      setRows(response.rows)
      setRejectedTokens(response.rejected)
      setTickerInput('')
      setWarning(null)
    } catch (error) {
      setRows(previousRows)
      setWarning(errorMessage(error, 'Ticker add failed.'))
    } finally {
      setIsAdding(false)
      tickerInputRef.current?.focus()
    }
  }

  async function handleRemove(row: EarningsWatchRow) {
    if (removingTicker) {
      return
    }
    const previousRows = rowsRef.current
    setRows(previousRows.filter((current) => current.ticker !== row.ticker))
    setRemovingTicker(row.ticker)
    try {
      await removeEarningsWatchTicker(row.ticker)
      setWarning(null)
    } catch (error) {
      setRows(previousRows)
      setWarning(errorMessage(error, 'Ticker removal failed.'))
    } finally {
      setRemovingTicker(null)
    }
  }

  async function handleReviewedChange(row: EarningsWatchRow, reviewed: boolean) {
    const previousRows = rowsRef.current
    pendingReviewedRef.current = {
      ...pendingReviewedRef.current,
      [row.ticker]: reviewed,
    }
    setPendingReviewed(pendingReviewedRef.current)
    setRows((current) =>
      current.map((item) =>
        item.ticker === row.ticker ? { ...item, reviewed } : item,
      ),
    )
    try {
      const updatedRow = await setEarningsWatchReviewed(row.ticker, reviewed)
      setRows((current) =>
        current.map((item) => (item.ticker === row.ticker ? updatedRow : item)),
      )
      setWarning(null)
    } catch (error) {
      setRows(previousRows)
      setWarning(errorMessage(error, 'Review update failed.'))
    } finally {
      const rest = { ...pendingReviewedRef.current }
      delete rest[row.ticker]
      pendingReviewedRef.current = rest
      setPendingReviewed(rest)
    }
  }

  async function handleClearReviewed() {
    setIsClearing(true)
    try {
      const response = await clearEarningsWatchReviews()
      setRows(response.rows)
      setWarning(null)
    } catch (error) {
      setWarning(errorMessage(error, 'Clear reviewed failed.'))
    } finally {
      setIsClearing(false)
    }
  }

  function handleSort(key: EarningsWatchSortKey) {
    setSort((current) => nextSort(current, key))
  }

  const metadataMessage = refreshMessage(refresh)
  const refreshWarning =
    refresh.state === 'failed' || refresh.state === 'cooldown'
      ? safeErrorMessage(refresh.error_category)
      : null

  return (
    <main className="flex min-w-0 w-full flex-col gap-6">
      <header className="flex flex-col gap-2">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">
              Earnings Watch
            </h1>
          </div>
          {rows.length > 0 ? (
            <Button
              className="w-fit cursor-pointer active:cursor-pointer"
              disabled={!hasReviewedRows || isClearing}
              variant="outline"
              onClick={handleClearReviewed}
            >
              Clear all reviewed
            </Button>
          ) : null}
        </div>
        {metadataMessage ? (
          <p className="text-sm text-muted-foreground">{metadataMessage}</p>
        ) : null}
      </header>

      {warning ? <Alert variant="destructive">{warning}</Alert> : null}
      {refreshWarning && refresh.state !== 'cooldown' ? (
        <Alert variant="muted">{refreshWarning}</Alert>
      ) : null}

      <section className="grid gap-3">
        <form className="grid gap-2" onSubmit={handleAddTickers}>
          <Field>
            <FieldLabel htmlFor="earnings-watch-tickers">Tickers</FieldLabel>
            <div className="flex gap-2">
              <Input
                aria-label="Tickers"
                autoCapitalize="characters"
                autoComplete="off"
                className="h-9 uppercase"
                id="earnings-watch-tickers"
                placeholder="AAPL, MSFT, BRK.B"
                ref={tickerInputRef}
                value={tickerInput}
                onChange={(event) => setTickerInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    event.currentTarget.form?.requestSubmit()
                  }
                }}
              />
              <Button
                className="h-9 cursor-pointer active:cursor-pointer"
                disabled={isAdding || parsedInput.valid.length === 0}
                type="submit"
              >
                <Plus data-icon="inline-start" />
                Add
              </Button>
            </div>
          </Field>
        </form>

        {rejectedTokens.length > 0 ? (
          <Alert variant="muted">
            Rejected: {rejectedTokens.slice(0, 8).join(', ')}
            {rejectedTokens.length > 8 ? '...' : ''}
          </Alert>
        ) : null}

        {rows.length > 0 ? (
          <div className="max-h-28 overflow-y-auto rounded-lg border bg-muted/10 p-2">
            <div className="flex flex-wrap gap-2">
              {rows.map((row) => (
                <Badge
                  className="h-7 gap-1 rounded-lg font-mono"
                  key={row.ticker}
                  variant="outline"
                >
                  {row.ticker}
                  <button
                    aria-label={`Remove ${row.ticker}`}
                    className="ml-1 inline-flex size-4 cursor-pointer items-center justify-center rounded-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={removingTicker === row.ticker}
                    type="button"
                    onClick={() => void handleRemove(row)}
                  >
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading saved tickers...</p>
      ) : rows.length > 0 ? (
        <section className="min-w-0 rounded-lg border">
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow>
                <SortableHead
                  label="Ticker"
                  sortKey="ticker"
                  sort={sort}
                  onSort={handleSort}
                />
                <SortableHead
                  label="Earnings date"
                  sortKey="earnings_date"
                  sort={sort}
                  onSort={handleSort}
                />
                <SortableHead
                  label="Status"
                  sortKey="status"
                  sort={sort}
                  onSort={handleSort}
                />
                <SortableHead
                  label="Reviewed"
                  sortKey="reviewed"
                  sort={sort}
                  onSort={handleSort}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayRows.map((row) => (
                <TableRow key={row.ticker}>
                  <TableCell className="sticky left-0 z-10 bg-background font-mono font-medium">
                    {row.ticker}
                  </TableCell>
                  <TableCell>{formatEarningsDate(row.earnings_date)}</TableCell>
                  <TableCell>
                    <StatusBadge status={row.status} />
                  </TableCell>
                  <TableCell className="sticky right-0 z-10 bg-background">
                    <Checkbox
                      aria-label={`Reviewed ${row.ticker}`}
                      checked={row.reviewed}
                      disabled={row.ticker in pendingReviewed}
                      onBlur={() => {
                        setFocusedReviewedTicker(null)
                        setDeferredReviewedRows(null)
                      }}
                      onCheckedChange={(checked) =>
                        void handleReviewedChange(row, checked === true)
                      }
                      onFocus={() => {
                        if (sortRef.current.key === 'reviewed') {
                          setFocusedReviewedTicker(row.ticker)
                          setDeferredReviewedRows(displayRows)
                        }
                      }}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      ) : null}
    </main>
  )
}

function SortableHead({
  label,
  sortKey,
  sort,
  onSort,
}: {
  label: string
  sortKey: EarningsWatchSortKey
  sort: EarningsWatchSort
  onSort: (key: EarningsWatchSortKey) => void
}) {
  const active = sort.key === sortKey
  const Icon = !active ? ArrowUpDown : sort.direction === 'asc' ? ArrowUp : ArrowDown

  return (
    <TableHead>
      <Button
        className="-ml-2 cursor-pointer active:cursor-pointer"
        size="sm"
        type="button"
        variant="ghost"
        onClick={() => onSort(sortKey)}
      >
        {label}
        <Icon className={cn('size-3.5', active ? 'opacity-100' : 'opacity-50')} />
      </Button>
    </TableHead>
  )
}

function StatusBadge({ status }: { status: EarningsWatchRow['status'] }) {
  return (
    <Badge
      variant={status === 'upcoming' ? 'secondary' : 'outline'}
      className={cn(status === 'no_date' && 'text-muted-foreground')}
    >
      {statusLabel(status)}
    </Badge>
  )
}

function parseTickerInput(value: string) {
  const valid: string[] = []
  const rejected: string[] = []
  const seen = new Set<string>()
  for (const token of value.trim().split(tickerTokenSeparator)) {
    if (!token) {
      continue
    }
    const ticker = token.toUpperCase()
    if (!tickerPattern.test(ticker)) {
      rejected.push(token)
      continue
    }
    if (!seen.has(ticker)) {
      seen.add(ticker)
      valid.push(ticker)
    }
  }
  return { valid, rejected }
}

function emptyRow(ticker: string, timestamp: string): EarningsWatchRow {
  return {
    ticker,
    reviewed: false,
    earnings_date: null,
    status: 'no_date',
    created_at: timestamp,
    updated_at: timestamp,
  }
}

function mergeRowsPreservingPendingReviews(
  nextRows: EarningsWatchRow[],
  pendingReviewed: Record<string, boolean>,
) {
  return nextRows.map((row) =>
    row.ticker in pendingReviewed
      ? { ...row, reviewed: pendingReviewed[row.ticker] }
      : row,
  )
}
