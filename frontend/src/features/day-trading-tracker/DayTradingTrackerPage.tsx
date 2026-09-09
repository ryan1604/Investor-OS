import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Plus, Save, Trash2 } from 'lucide-react'

import {
  fetchDayTradingMonth,
  replaceDayTradingDateTrades,
} from '@/api/dayTradingTracker'
import { errorMessage as requestErrorMessage, isAbortError } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  buildMonthWeeks,
  calculateDayTradingStats,
  calculateMonthlyDayTradingStats,
  canNavigateNext,
  canNavigatePrevious,
  currentIsoDate,
  draftRowsFromStoredRows,
  initialMonth,
  monthLabel,
  newDayTradeDraftRow,
  nextMonth,
  previousMonthKey,
  requestRowsFromDraftRows,
  validateDayTradeDraftRows,
  type CalendarDay,
  type DayTradeDraftField,
  type DayTradeDraftIssue,
  type DayTradeDraftRow,
} from '@/features/day-trading-tracker/lib/dayTradingTracker'
import { formatCurrency, formatPercentValue, signedTextClassName } from '@/lib/format'
import { cn } from '@/lib/utils'

const weekDayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

type SaveStatus = 'idle' | 'loading' | 'saving' | 'saved' | 'error'

export function DayTradingTrackerPage() {
  const today = useMemo(() => currentIsoDate(), [])
  const [month, setMonth] = useState(() => initialMonth(today))
  const [openDate, setOpenDate] = useState<string | null>(null)
  const [draftRowsByDate, setDraftRowsByDate] = useState<
    Record<string, DayTradeDraftRow[]>
  >({})
  const [dirtyDates, setDirtyDates] = useState<Set<string>>(() => new Set())
  const dirtyDatesRef = useRef(dirtyDates)
  const [issuesByDate, setIssuesByDate] = useState<
    Record<string, DayTradeDraftIssue[]>
  >({})
  const [status, setStatus] = useState<SaveStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    dirtyDatesRef.current = dirtyDates
  }, [dirtyDates])

  useEffect(() => {
    const controller = new AbortController()

    async function loadMonth() {
      setStatus('loading')
      setError(null)

      try {
        const response = await fetchDayTradingMonth(month, controller.signal)
        if (controller.signal.aborted) {
          return
        }

        const loadedRowsByDate = Object.fromEntries(
          response.days.map((day) => [
            day.date,
            draftRowsFromStoredRows(day.trades),
          ]),
        )
        setDraftRowsByDate((current) => {
          const next = { ...current }

          Object.entries(loadedRowsByDate).forEach(([date, rows]) => {
            if (!dirtyDatesRef.current.has(date)) {
              next[date] = rows
            }
          })

          return next
        })
        setStatus('idle')
      } catch (requestError) {
        if (!isAbortError(requestError)) {
          setStatus('error')
          setError(errorMessage(requestError))
        }
      }
    }

    void loadMonth()

    return () => {
      controller.abort()
    }
  }, [month])

  const weeks = useMemo(() => buildMonthWeeks(month, today), [month, today])
  const visibleRowsByDate = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(draftRowsByDate).filter(([date]) =>
          date.startsWith(`${month}-`),
        ),
      ),
    [draftRowsByDate, month],
  )
  const monthlyStats = useMemo(
    () => calculateMonthlyDayTradingStats(visibleRowsByDate),
    [visibleRowsByDate],
  )
  const selectedRows = openDate ? draftRowsByDate[openDate] ?? [] : []
  const selectedIssues = openDate ? issuesByDate[openDate] ?? [] : []
  const selectedStats = calculateDayTradingStats(selectedRows)

  async function saveSelectedDate() {
    if (!openDate) {
      return
    }

    const issues = validateDayTradeDraftRows(selectedRows)
    setIssuesByDate((current) => ({ ...current, [openDate]: issues }))
    if (issues.length > 0) {
      setError('Resolve day trade validation before saving.')
      setStatus('error')
      return
    }

    setStatus('saving')
    setError(null)

    try {
      const savedDay = await replaceDayTradingDateTrades(openDate, {
        trades: requestRowsFromDraftRows(selectedRows),
      })
      setDraftRowsByDate((current) => ({
        ...current,
        [openDate]: draftRowsFromStoredRows(savedDay.trades),
      }))
      setDirtyDates((current) => {
        const next = new Set(current)
        next.delete(openDate)
        return next
      })
      setIssuesByDate((current) => ({ ...current, [openDate]: [] }))
      setStatus('saved')
    } catch (requestError) {
      setStatus('error')
      setError(errorMessage(requestError))
    }
  }

  function updateSelectedRows(updater: (rows: DayTradeDraftRow[]) => DayTradeDraftRow[]) {
    if (!openDate) {
      return
    }

    setDraftRowsByDate((current) => ({
      ...current,
      [openDate]: updater(current[openDate] ?? []),
    }))
    setDirtyDates((current) => new Set(current).add(openDate))
    setIssuesByDate((current) => ({ ...current, [openDate]: [] }))
    setStatus('idle')
    setError(null)
  }

  function addRow() {
    updateSelectedRows((rows) => [...rows, newDayTradeDraftRow(createLocalRowId())])
  }

  function updateRow(
    localId: string,
    field: DayTradeDraftField,
    value: string,
  ) {
    updateSelectedRows((rows) =>
      rows.map((row) =>
        row.localId === localId ? { ...row, [field]: value } : row,
      ),
    )
  }

  function deleteRow(localId: string) {
    updateSelectedRows((rows) => rows.filter((row) => row.localId !== localId))
  }

  return (
    <main className="flex w-full min-w-0 flex-col gap-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Day Trading Tracker
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            aria-label="Previous month"
            disabled={!canNavigatePrevious(month)}
            size="icon"
            type="button"
            variant="outline"
            onClick={() => setMonth(previousMonthKey(month))}
          >
            <ChevronLeft />
          </Button>
          <div className="min-w-44 text-center text-xl font-semibold tabular-nums">
            {monthLabel(month)}
          </div>
          <Button
            aria-label="Next month"
            disabled={!canNavigateNext(month, today)}
            size="icon"
            type="button"
            variant="outline"
            onClick={() => setMonth(nextMonth(month))}
          >
            <ChevronRight />
          </Button>
        </div>
      </header>

      <MonthlyStats stats={monthlyStats} />

      {error ? <Alert variant="destructive">{error}</Alert> : null}
      {status === 'loading' ? (
        <div className="text-sm text-muted-foreground" role="status">
          Loading month...
        </div>
      ) : null}

      <Collapsible
        open={openDate !== null}
        onOpenChange={(open) => {
          if (!open) {
            setOpenDate(null)
          }
        }}
      >
        <section className="overflow-hidden rounded-lg border border-border bg-background">
          <div className="grid grid-cols-7 border-b border-border bg-muted/20">
            {weekDayLabels.map((label) => (
              <div
                className="border-r border-border p-3 text-sm font-medium last:border-r-0"
                key={label}
              >
                {label}
              </div>
            ))}
          </div>

          <div>
            {weeks.map((week) => {
              const openDateInWeek = week.find((day) => day.date === openDate)

              return (
                <div key={week[0].date}>
                  <div className="grid grid-cols-7 border-b border-border last:border-b-0">
                    {week.map((day) => (
                      <CalendarDayCell
                        day={day}
                        key={day.date}
                        rows={draftRowsByDate[day.date] ?? []}
                        isSelected={day.date === openDate}
                        onSelect={() => setOpenDate(day.date)}
                      />
                    ))}
                  </div>
                  {openDateInWeek ? (
                    <CollapsibleContent forceMount>
                      <DayTradeTable
                        date={openDateInWeek.date}
                        issues={selectedIssues}
                        rows={selectedRows}
                        stats={selectedStats}
                        isSaving={status === 'saving'}
                        onAddRow={addRow}
                        onDeleteRow={deleteRow}
                        onSave={() => void saveSelectedDate()}
                        onUpdateRow={updateRow}
                      />
                    </CollapsibleContent>
                  ) : null}
                </div>
              )
            })}
          </div>
        </section>
      </Collapsible>
    </main>
  )
}

function MonthlyStats({ stats }: { stats: ReturnType<typeof calculateMonthlyDayTradingStats> }) {
  return (
    <section className="grid gap-3 rounded-lg border border-border bg-muted/20 p-3 sm:grid-cols-5">
      <StatBlock label="Win days" value={String(stats.winDays)} tone="positive" />
      <StatBlock label="Loss days" value={String(stats.lossDays)} tone="negative" />
      <StatBlock label="Trades" value={String(stats.completedTrades)} />
      <StatBlock
        label="Win %"
        value={stats.winRate === null ? '-' : formatPercentValue(stats.winRate * 100)}
      />
      <StatBlock
        label="PnL"
        value={formatCurrency(stats.pnl)}
        tone={stats.pnl > 0 ? 'positive' : stats.pnl < 0 ? 'negative' : undefined}
      />
    </section>
  )
}

function StatBlock({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'positive' | 'negative'
}) {
  return (
    <div>
      <div className="text-sm text-muted-foreground">{label}</div>
      <div
        className={cn(
          'text-xl font-semibold tabular-nums',
          tone === 'positive' ? 'text-emerald-500' : null,
          tone === 'negative' ? 'text-red-500' : null,
        )}
      >
        {value}
      </div>
    </div>
  )
}

function CalendarDayCell({
  day,
  rows,
  isSelected,
  onSelect,
}: {
  day: CalendarDay
  rows: DayTradeDraftRow[]
  isSelected: boolean
  onSelect: () => void
}) {
  const stats = calculateDayTradingStats(rows)
  const hasTrades = stats.completedTrades > 0
  const content = (
    <>
      <div className="flex justify-end text-base font-semibold tabular-nums">
        {day.dayOfMonth}
      </div>
      <div className="mt-auto grid gap-1 text-left">
        {hasTrades ? (
          <>
            <div
              className={cn(
                'font-semibold tabular-nums',
                signedTextClassName(stats.pnl),
              )}
            >
              {formatCurrency(stats.pnl)}
            </div>
            <div>{stats.completedTrades} trades</div>
            <div>
              W: {stats.wins} L: {stats.losses}
            </div>
            <div>
              (
              {stats.winRate === null
                ? '-'
                : formatPercentValue(stats.winRate * 100)}
              )
            </div>
          </>
        ) : (
          <div className="text-muted-foreground">No trades</div>
        )}
      </div>
    </>
  )
  const className = cn(
    'flex min-h-32 w-full flex-col border-r border-border p-3 text-sm last:border-r-0',
    day.isAllowed
      ? 'cursor-pointer text-foreground hover:bg-muted/30'
      : 'cursor-not-allowed text-muted-foreground/45',
    isSelected ? 'bg-muted/40 ring-1 ring-inset ring-primary/40' : null,
  )

  if (!day.isAllowed) {
    return (
      <button type="button" className={className} disabled>
        {content}
      </button>
    )
  }

  return (
    <CollapsibleTrigger asChild>
      <button
        type="button"
        aria-label={`Open trades for ${day.date}`}
        className={className}
        onClick={onSelect}
      >
        {content}
      </button>
    </CollapsibleTrigger>
  )
}

function DayTradeTable({
  date,
  issues,
  rows,
  stats,
  isSaving,
  onAddRow,
  onDeleteRow,
  onSave,
  onUpdateRow,
}: {
  date: string
  issues: DayTradeDraftIssue[]
  rows: DayTradeDraftRow[]
  stats: ReturnType<typeof calculateDayTradingStats>
  isSaving: boolean
  onAddRow: () => void
  onDeleteRow: (localId: string) => void
  onSave: () => void
  onUpdateRow: (
    localId: string,
    field: DayTradeDraftField,
    value: string,
  ) => void
}) {
  return (
    <section className="border-b border-border bg-muted/10">
      <div className="flex flex-col gap-3 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <h2 className="font-medium">{date}</h2>
          <Badge variant="outline">{formatCurrency(stats.pnl)}</Badge>
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onAddRow}>
            <Plus />
            Add row
          </Button>
          <Button type="button" onClick={onSave} disabled={isSaving}>
            <Save />
            {isSaving ? 'Saving...' : 'Save trades'}
          </Button>
        </div>
      </div>

      <Table className="table-fixed text-xs">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[23%] text-right">Buy</TableHead>
            <TableHead className="w-[23%] text-right">Sell</TableHead>
            <TableHead className="w-[19%] text-right">Size</TableHead>
            <TableHead className="w-[19%] text-right">Fee</TableHead>
            <TableHead className="w-[16%] text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={5}
                className="h-20 text-center text-muted-foreground"
              >
                Add a row to log trades for this day.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row, index) => (
              <TableRow key={row.localId}>
                <TableCell>
                  <NumberCell
                    label={`Buy row ${index + 1}`}
                    value={row.buy}
                    onChange={(value) => onUpdateRow(row.localId, 'buy', value)}
                  />
                  <FieldIssue issues={issues} localId={row.localId} field="buy" />
                </TableCell>
                <TableCell>
                  <NumberCell
                    label={`Sell row ${index + 1}`}
                    value={row.sell}
                    onChange={(value) => onUpdateRow(row.localId, 'sell', value)}
                  />
                  <FieldIssue issues={issues} localId={row.localId} field="sell" />
                </TableCell>
                <TableCell>
                  <NumberCell
                    label={`Size row ${index + 1}`}
                    value={row.size}
                    onChange={(value) => onUpdateRow(row.localId, 'size', value)}
                  />
                  <FieldIssue issues={issues} localId={row.localId} field="size" />
                </TableCell>
                <TableCell>
                  <NumberCell
                    label={`Fee row ${index + 1}`}
                    value={row.fee}
                    onChange={(value) => onUpdateRow(row.localId, 'fee', value)}
                  />
                  <FieldIssue issues={issues} localId={row.localId} field="fee" />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Delete row ${index + 1}`}
                      onClick={() => onDeleteRow(row.localId)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell colSpan={3}>Total</TableCell>
            <TableCell className="text-right tabular-nums">
              {stats.completedTrades} trades
            </TableCell>
            <TableCell className="text-right font-medium tabular-nums">
              {formatCurrency(stats.pnl)}
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </section>
  )
}

function NumberCell({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <Input
      aria-label={label}
      className="text-right tabular-nums"
      inputMode="decimal"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function FieldIssue({
  issues,
  localId,
  field,
}: {
  issues: DayTradeDraftIssue[]
  localId: string
  field: DayTradeDraftField
}) {
  const issue = issues.find(
    (candidate) => candidate.localId === localId && candidate.field === field,
  )

  return issue ? (
    <div className="mt-1 text-left text-xs text-destructive">{issue.message}</div>
  ) : null
}

function errorMessage(error: unknown) {
  return requestErrorMessage(error, 'Day trading tracker request failed.')
}

function createLocalRowId() {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
