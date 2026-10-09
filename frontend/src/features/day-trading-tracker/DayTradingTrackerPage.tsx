import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  calculateDayTradingStats,
  calculateMonthlyDayTradingStats,
  canNavigateNext,
  canNavigatePrevious,
  monthLabel,
  nextMonth,
  previousMonthKey,
  type CalendarDay,
  type DayTradeDraftRow,
} from '@/features/day-trading-tracker/lib/dayTradingTracker'
import { formatCurrency, formatPercentValue, signedTextClassName } from '@/lib/format'
import { cn } from '@/lib/utils'

import { DayTradeTable } from '@/features/day-trading-tracker/components/DayTradeTable'
import { useDayTradingMonth } from '@/features/day-trading-tracker/hooks/useDayTradingMonth'

const weekDayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function DayTradingTrackerPage() {
  const {
    today, month, setMonth, openDate, setOpenDate, draftRowsByDate, weeks,
    monthlyStats, selectedRows, selectedIssues, selectedStats, status, error,
    saveSelectedDate, addRow, updateRow, deleteRow,
  } = useDayTradingMonth()

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
