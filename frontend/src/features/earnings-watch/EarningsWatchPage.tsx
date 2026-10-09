import { ArrowDown, ArrowUp, ArrowUpDown, Plus, X } from 'lucide-react'

import type { EarningsWatchRow } from '@/api/earningsWatch'
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
  statusLabel,
  type EarningsWatchSort,
  type EarningsWatchSortKey,
} from '@/features/earnings-watch/lib/earningsWatch'
import { cn } from '@/lib/utils'

import { useEarningsWatch } from '@/features/earnings-watch/hooks/useEarningsWatch'

export function EarningsWatchPage() {
  const {
    rows, refresh, tickerInput, setTickerInput, tickerInputRef, rejectedTokens,
    warning, isLoading, isAdding, isClearing, removingTicker, pendingReviewed,
    sort, displayRows, hasReviewedRows, parsedInput, metadataMessage, refreshWarning,
    setFocusedReviewedTicker, setDeferredReviewedRows,
    handleAddTickers, handleRemove, handleReviewedChange, handleClearReviewed, handleSort,
  } = useEarningsWatch()

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
                        if (sort.key === 'reviewed') {
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
