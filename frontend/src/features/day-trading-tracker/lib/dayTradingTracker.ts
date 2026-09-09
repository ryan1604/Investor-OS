import type {
  DayTradingRow,
  DayTradingRowRequest,
} from '@/api/dayTradingTracker'

export const DAY_TRADING_MIN_DATE = '2026-08-01'

export type DayTradeDraftRow = {
  localId: string
  id: string | null
  buy: string
  sell: string
  size: string
  fee: string
}

export type DayTradeDraftField = keyof Pick<
  DayTradeDraftRow,
  'buy' | 'sell' | 'size' | 'fee'
>

export type DayTradeDraftIssue = {
  localId: string
  field: DayTradeDraftField
  message: string
}

export type CalendarDay = {
  date: string
  dayOfMonth: number
  isCurrentMonth: boolean
  isAllowed: boolean
}

export type CompletedDayTrade = {
  row: DayTradeDraftRow
  buy: number
  sell: number
  size: number
  fee: number
  grossPnl: number
}

export type DayTradingStats = {
  completedTrades: number
  wins: number
  losses: number
  winRate: number | null
  pnl: number
}

export type MonthlyDayTradingStats = DayTradingStats & {
  winDays: number
  lossDays: number
}

export function currentIsoDate() {
  return isoDate(new Date())
}

export function currentMonthKey(today = currentIsoDate()) {
  return today.slice(0, 7)
}

export function initialMonth(today = currentIsoDate()) {
  return maxMonthKey(DAY_TRADING_MIN_DATE.slice(0, 7), currentMonthKey(today))
}

export function previousMonthKey(month: string) {
  const [year, monthNumber] = month.split('-').map(Number)
  const date = new Date(year, monthNumber - 2, 1)
  return monthKey(date)
}

export function nextMonth(month: string) {
  const [year, monthNumber] = month.split('-').map(Number)
  const date = new Date(year, monthNumber, 1)
  return monthKey(date)
}

export function canNavigatePrevious(month: string) {
  return month > DAY_TRADING_MIN_DATE.slice(0, 7)
}

export function canNavigateNext(month: string, today = currentIsoDate()) {
  return month < currentMonthKey(today)
}

export function monthLabel(month: string) {
  const [year, monthNumber] = month.split('-').map(Number)
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    year: 'numeric',
  }).format(new Date(year, monthNumber - 1, 1))
}

export function buildMonthWeeks(month: string, today = currentIsoDate()) {
  const [year, monthNumber] = month.split('-').map(Number)
  const firstDay = new Date(year, monthNumber - 1, 1)
  const startOffset = (firstDay.getDay() + 6) % 7
  const startDate = new Date(year, monthNumber - 1, 1 - startOffset)
  const weeks: CalendarDay[][] = []

  for (let weekIndex = 0; weekIndex < 6; weekIndex += 1) {
    const week: CalendarDay[] = []
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
      const date = new Date(startDate)
      date.setDate(startDate.getDate() + weekIndex * 7 + dayIndex)
      const dateKey = isoDate(date)
      const isCurrentMonth = date.getMonth() === monthNumber - 1
      week.push({
        date: dateKey,
        dayOfMonth: date.getDate(),
        isCurrentMonth,
        isAllowed:
          isCurrentMonth &&
          dateKey >= DAY_TRADING_MIN_DATE &&
          dateKey <= today,
      })
    }
    weeks.push(week)
  }

  return weeks
}

export function newDayTradeDraftRow(
  localId: string,
): DayTradeDraftRow {
  return {
    localId,
    id: null,
    buy: '',
    sell: '',
    size: '',
    fee: '2',
  }
}

export function draftRowsFromStoredRows(rows: DayTradingRow[]) {
  return rows
    .slice()
    .sort((first, second) => first.display_order - second.display_order)
    .map((row) => ({
      localId: row.id,
      id: row.id,
      buy: draftNumberText(row.buy),
      sell: draftNumberText(row.sell),
      size: draftNumberText(row.size),
      fee: draftNumberText(row.fee ?? 2),
    }))
}

export function requestRowsFromDraftRows(
  rows: DayTradeDraftRow[],
): DayTradingRowRequest[] {
  return rows.map((row, index) => ({
    id: row.id,
    display_order: index + 1,
    buy: validDecimal(row.buy),
    sell: validDecimal(row.sell),
    size: validPositiveWholeNumber(row.size),
    fee: validNonNegativeDecimal(row.fee),
  }))
}

export function validateDayTradeDraftRows(rows: DayTradeDraftRow[]) {
  return rows.flatMap((row) => validateDayTradeDraftRow(row))
}

export function completedDayTrades(rows: DayTradeDraftRow[]) {
  return rows.flatMap((row): CompletedDayTrade[] => {
    const buy = validDecimal(row.buy)
    const sell = validDecimal(row.sell)
    const size = validPositiveWholeNumber(row.size)
    const fee = validNonNegativeDecimal(row.fee)

    if (buy === null || sell === null || size === null || fee === null) {
      return []
    }

    return [
      {
        row,
        buy,
        sell,
        size,
        fee,
        grossPnl: (sell - buy) * size * 100,
      },
    ]
  })
}

export function calculateDayTradingStats(rows: DayTradeDraftRow[]): DayTradingStats {
  const completedTrades = completedDayTrades(rows)
  const grossPnl = completedTrades.reduce((total, trade) => total + trade.grossPnl, 0)
  const commission = completedTrades.reduce(
    (total, trade) => total + Math.abs(trade.size) * 2 * trade.fee,
    0,
  )
  const wins = completedTrades.filter((trade) => trade.grossPnl > 0).length
  const losses = completedTrades.filter((trade) => trade.grossPnl < 0).length
  const winLossTotal = wins + losses

  return {
    completedTrades: completedTrades.length,
    wins,
    losses,
    winRate: winLossTotal === 0 ? null : wins / winLossTotal,
    pnl: grossPnl - commission,
  }
}

export function calculateMonthlyDayTradingStats(
  rowsByDate: Record<string, DayTradeDraftRow[]>,
): MonthlyDayTradingStats {
  const dayStats = Object.values(rowsByDate).map(calculateDayTradingStats)
  const totals = dayStats.reduce(
    (total, stats) => ({
      completedTrades: total.completedTrades + stats.completedTrades,
      wins: total.wins + stats.wins,
      losses: total.losses + stats.losses,
      pnl: total.pnl + stats.pnl,
      winDays: total.winDays + (stats.completedTrades > 0 && stats.pnl > 0 ? 1 : 0),
      lossDays:
        total.lossDays + (stats.completedTrades > 0 && stats.pnl < 0 ? 1 : 0),
    }),
    {
      completedTrades: 0,
      wins: 0,
      losses: 0,
      pnl: 0,
      winDays: 0,
      lossDays: 0,
    },
  )
  const winLossTotal = totals.wins + totals.losses

  return {
    ...totals,
    winRate: winLossTotal === 0 ? null : totals.wins / winLossTotal,
  }
}

function validateDayTradeDraftRow(row: DayTradeDraftRow): DayTradeDraftIssue[] {
  const issues: DayTradeDraftIssue[] = []

  if (parseOptionalDecimal(row.buy) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'buy',
      message: 'Buy must be a valid number.',
    })
  }
  if (parseOptionalDecimal(row.sell) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'sell',
      message: 'Sell must be a valid number.',
    })
  }
  if (parseOptionalPositiveWholeNumber(row.size) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'size',
      message: 'Size must be a positive whole number.',
    })
  }
  if (parseOptionalNonNegativeDecimal(row.fee) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'fee',
      message: 'Fee must be zero or greater.',
    })
  }

  return issues
}

function parseOptionalDecimal(value: string) {
  const normalizedValue = value.trim()
  if (!normalizedValue) {
    return null
  }

  const parsedValue = Number(normalizedValue)
  return Number.isFinite(parsedValue) ? parsedValue : 'invalid'
}

function parseOptionalPositiveWholeNumber(value: string) {
  const normalizedValue = value.trim()
  if (!normalizedValue) {
    return null
  }

  if (!/^\d+$/.test(normalizedValue)) {
    return 'invalid'
  }

  const parsedValue = Number(normalizedValue)
  return parsedValue > 0 ? parsedValue : 'invalid'
}

function validDecimal(value: string) {
  const parsedValue = parseOptionalDecimal(value)
  return parsedValue === 'invalid' ? null : parsedValue
}

function validPositiveWholeNumber(value: string) {
  const parsedValue = parseOptionalPositiveWholeNumber(value)
  return parsedValue === 'invalid' ? null : parsedValue
}

function parseOptionalNonNegativeDecimal(value: string) {
  const parsedValue = parseOptionalDecimal(value)
  if (parsedValue === null || parsedValue === 'invalid') {
    return parsedValue
  }

  return parsedValue >= 0 ? parsedValue : 'invalid'
}

function validNonNegativeDecimal(value: string) {
  const parsedValue = parseOptionalNonNegativeDecimal(value)
  return parsedValue === 'invalid' ? null : parsedValue
}

function draftNumberText(value: number | null) {
  return value === null ? '' : String(value)
}

function isoDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(
    2,
    '0',
  )}-${String(date.getDate()).padStart(2, '0')}`
}

function monthKey(date: Date) {
  return isoDate(date).slice(0, 7)
}

function maxMonthKey(first: string, second: string) {
  return first > second ? first : second
}
