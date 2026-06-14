import {
  type OptionsTradeMonth,
  type OptionsTradeRowRequest,
  type OptionsTradeRow,
  type OptionsTradeStatus,
} from '@/api/optionsTradeTrackers'
import { formatCurrency } from '@/lib/format'

type CompletedOptionsTrade = OptionsTradeRow & {
  status: 'Completed'
  strategy: string
  ticker: string
  month: OptionsTradeMonth
  size: number
  strike_price: number
  credit_debit: number
}

export type CompletedTradeProjection = {
  row: CompletedOptionsTrade
  pnl: number
}

type StrategyStatsRow = {
  strategy: string
  months: Record<OptionsTradeMonth, number>
  total: number
  count: number
  average: number | null
}

export type StrategyStatsTable = {
  rows: StrategyStatsRow[]
  monthTotals: Record<OptionsTradeMonth, number>
  total: number
  count: number
  average: number | null
}

export type StackedMonthlyChartRow = {
  month: OptionsTradeMonth
  label: string
} & Record<string, number | string>

type NetMonthlyChartRow = {
  month: OptionsTradeMonth
  label: string
  total: number
}

export type StrategyCountPieSlice = {
  strategy: string
  count: number
}

export type TradeDraftRow = {
  localId: string
  id: string | null
  strategy: string
  ticker: string
  month: OptionsTradeMonth
  size: string
  strikePrice: string
  creditDebit: string
  exit: string
  status: OptionsTradeStatus
}

export type TradeDraftField = keyof Omit<TradeDraftRow, 'id' | 'localId'>

export type TradeDraftValidationIssue = {
  localId: string
  field: TradeDraftField | 'row'
  message: string
}

export const OPTIONS_TRADE_MONTHS = [
  'jan',
  'feb',
  'mar',
  'apr',
  'may',
  'jun',
  'jul',
  'aug',
  'sep',
  'oct',
  'nov',
  'dec',
] as const satisfies readonly OptionsTradeMonth[]

export const OPTIONS_TRADE_MONTH_LABELS: Record<OptionsTradeMonth, string> = {
  jan: 'Jan',
  feb: 'Feb',
  mar: 'Mar',
  apr: 'Apr',
  may: 'May',
  jun: 'Jun',
  jul: 'Jul',
  aug: 'Aug',
  sep: 'Sep',
  oct: 'Oct',
  nov: 'Nov',
  dec: 'Dec',
}

export function newTradeDraftRow(
  localId: string,
  month: OptionsTradeMonth = currentTradeMonth(),
): TradeDraftRow {
  return {
    localId,
    id: null,
    strategy: '',
    ticker: '',
    month,
    size: '',
    strikePrice: '',
    creditDebit: '',
    exit: '',
    status: 'In Progress',
  }
}

export function tradeDraftRowFromStoredRow(row: OptionsTradeRow): TradeDraftRow {
  return {
    localId: row.id,
    id: row.id,
    strategy: row.strategy ?? '',
    ticker: row.ticker ?? '',
    month: row.month ?? currentTradeMonth(),
    size: draftNumberText(row.size),
    strikePrice: draftNumberText(row.strike_price),
    creditDebit: draftNumberText(row.credit_debit),
    exit: draftNumberText(row.exit),
    status: row.status,
  }
}

export function storedRowFromTradeDraft(
  row: TradeDraftRow,
  displayOrder: number,
): OptionsTradeRow {
  return {
    id: row.id ?? row.localId,
    display_order: displayOrder,
    status: row.status,
    strategy: normalizeNullableStrategy(row.strategy),
    ticker: normalizeTickerInput(row.ticker),
    month: row.month,
    size: validSignedNumber(row.size),
    strike_price: validPositiveCurrency(row.strikePrice),
    credit_debit: validPositiveCurrency(row.creditDebit),
    exit: validExitCurrency(row.exit),
    created_at: '',
    updated_at: '',
  }
}

export function tradeRequestFromDraftRow(
  row: TradeDraftRow,
  displayOrder: number,
): OptionsTradeRowRequest {
  const storedRow = storedRowFromTradeDraft(row, displayOrder)

  return {
    id: row.id,
    display_order: storedRow.display_order,
    status: storedRow.status,
    strategy: storedRow.strategy,
    ticker: storedRow.ticker,
    month: storedRow.month,
    size: storedRow.size,
    strike_price: storedRow.strike_price,
    credit_debit: storedRow.credit_debit,
    exit: storedRow.exit,
  }
}

export function validateTradeDraftRows(rows: TradeDraftRow[]) {
  return rows.flatMap((row) => validateTradeDraftRow(row))
}

function currentTradeMonth(): OptionsTradeMonth {
  return OPTIONS_TRADE_MONTHS[new Date().getMonth()]
}

function normalizeTickerInput(value: string | null | undefined) {
  const normalizedValue = value?.trim().toUpperCase() ?? ''
  return normalizedValue || null
}

export function normalizeTickerDraft(value: string) {
  return value.trim().toUpperCase()
}

export function normalizeStrategyOption(value: string) {
  const normalizedValue = value.trim().split(/\s+/).filter(Boolean).join(' ')

  if (!normalizedValue) {
    return ''
  }

  return normalizedValue.toUpperCase()
}

export function parseCurrencyInput(
  value: string | number | null | undefined,
  options: { allowBlank?: boolean; allowZero?: boolean } = {},
) {
  const parsedValue = parseDecimalInput(value, options.allowBlank ?? false)

  if (parsedValue === 'invalid' || parsedValue === null) {
    return parsedValue
  }

  if (parsedValue < 0) {
    return 'invalid'
  }

  if (parsedValue === 0 && !options.allowZero) {
    return 'invalid'
  }

  return parsedValue
}

export function formatCurrencyInput(value: number | null | undefined) {
  return value === null || value === undefined ? '' : formatCurrency(value)
}

export function formatPnl(value: number | null) {
  return value === null ? '' : formatCurrency(value)
}

function completedValidTrade(row: OptionsTradeRow) {
  if (row.status !== 'Completed') {
    return null
  }

  if (
    row.strategy === null ||
    row.ticker === null ||
    row.month === null ||
    row.size === null ||
    row.strike_price === null ||
    row.credit_debit === null
  ) {
    return null
  }

  if (
    row.strategy.trim() === '' ||
    row.ticker.trim() === '' ||
    !isOptionsTradeMonth(row.month) ||
    !isFiniteNumber(row.size) ||
    row.size === 0 ||
    !isFiniteNumber(row.strike_price) ||
    !isFiniteNumber(row.credit_debit) ||
    row.credit_debit <= 0 ||
    row.strike_price <= 0 ||
    (row.exit !== null && (!isFiniteNumber(row.exit) || row.exit < 0))
  ) {
    return null
  }

  return row as CompletedOptionsTrade
}

export function projectCompletedValidTrades(rows: OptionsTradeRow[]) {
  return rows.flatMap((row): CompletedTradeProjection[] => {
    const completedTrade = completedValidTrade(row)
    if (completedTrade === null) {
      return []
    }

    return [
      {
        row: completedTrade,
        pnl: calculateCompletedTradePnl(completedTrade),
      },
    ]
  })
}

export function calculateTradesFooterTotal(
  completedTrades: CompletedTradeProjection[],
) {
  return completedTrades.reduce((total, trade) => total + trade.pnl, 0)
}

export function deriveStrategyStats(
  completedTrades: CompletedTradeProjection[],
  strategyOptions: string[],
): StrategyStatsTable {
  const statsRows = normalizedStrategyOptions(strategyOptions).map((strategy) =>
    emptyStrategyStatsRow(strategy),
  )
  const statsByStrategy = new Map(
    statsRows.map((statsRow) => [statsRow.strategy, statsRow]),
  )

  completedTrades.forEach(({ row, pnl }) => {
    const statsRow =
      statsByStrategy.get(row.strategy) ?? emptyStrategyStatsRow(row.strategy)

    if (!statsByStrategy.has(row.strategy)) {
      statsByStrategy.set(row.strategy, statsRow)
      statsRows.push(statsRow)
    }

    statsRow.months[row.month] += pnl
    statsRow.total += pnl
    statsRow.count += Math.abs(row.size)
  })

  statsRows.forEach((row) => {
    row.average = row.count === 0 ? null : row.total / row.count
  })

  const monthTotals = emptyMonthTotals()
  let total = 0
  let count = 0

  statsRows.forEach((row) => {
    OPTIONS_TRADE_MONTHS.forEach((month) => {
      monthTotals[month] += row.months[month]
    })
    total += row.total
    count += row.count
  })

  return {
    rows: statsRows,
    monthTotals,
    total,
    count,
    average: count === 0 ? null : total / count,
  }
}

export function formatAverage(value: number | null) {
  return value === null ? '-' : formatCurrency(value)
}

export function deriveStackedMonthlyChartData(
  completedTrades: CompletedTradeProjection[],
  strategyOptions: string[],
) {
  const strategies = normalizedStrategyOptions(strategyOptions)
  const chartRows = OPTIONS_TRADE_MONTHS.map((month) => {
    const chartRow: StackedMonthlyChartRow = {
      month,
      label: OPTIONS_TRADE_MONTH_LABELS[month],
    }

    strategies.forEach((strategy) => {
      chartRow[strategy] = 0
    })

    return chartRow
  })

  completedTrades.forEach(({ row, pnl }) => {
    const chartRow = chartRows[OPTIONS_TRADE_MONTHS.indexOf(row.month)]
    chartRow[row.strategy] = numericChartValue(chartRow[row.strategy]) + pnl
  })

  return chartRows
}

export function deriveNetMonthlyChartData(
  completedTrades: CompletedTradeProjection[],
) {
  const chartRows: NetMonthlyChartRow[] = OPTIONS_TRADE_MONTHS.map((month) => ({
    month,
    label: OPTIONS_TRADE_MONTH_LABELS[month],
    total: 0,
  }))

  completedTrades.forEach(({ row, pnl }) => {
    chartRows[OPTIONS_TRADE_MONTHS.indexOf(row.month)].total += pnl
  })

  return chartRows
}

export function deriveStrategyCountPieData(
  completedTrades: CompletedTradeProjection[],
) {
  const countsByStrategy = new Map<string, number>()

  completedTrades.forEach(({ row }) => {
    countsByStrategy.set(
      row.strategy,
      (countsByStrategy.get(row.strategy) ?? 0) + Math.abs(row.size),
    )
  })

  return [...countsByStrategy.entries()]
    .map(([strategy, count]) => ({ strategy, count }))
    .sort((first, second) => first.strategy.localeCompare(second.strategy))
}

function normalizedStrategyOptions(strategyOptions: string[]) {
  return strategyOptions
    .map((strategy) => strategy.trim())
    .filter((strategy, index, strategies) => {
      return strategy !== '' && strategies.indexOf(strategy) === index
    })
}

function calculateCompletedTradePnl(trade: CompletedOptionsTrade) {
  const exit = trade.exit ?? 0
  return (trade.credit_debit * 100 - exit * 100 - 2) * -trade.size
}

function emptyStrategyStatsRow(strategy: string): StrategyStatsRow {
  return {
    strategy,
    months: emptyMonthTotals(),
    total: 0,
    count: 0,
    average: null,
  }
}

function emptyMonthTotals() {
  return Object.fromEntries(
    OPTIONS_TRADE_MONTHS.map((month) => [month, 0]),
  ) as Record<OptionsTradeMonth, number>
}

function parseDecimalInput(
  value: string | number | null | undefined,
  allowBlank: boolean,
) {
  if (value === null || value === undefined) {
    return allowBlank ? null : 'invalid'
  }

  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 'invalid'
  }

  const normalizedValue = value.trim()
  if (!normalizedValue) {
    return allowBlank ? null : 'invalid'
  }

  const numericValue = Number(normalizedValue)
  return Number.isFinite(numericValue) ? numericValue : 'invalid'
}

function validateTradeDraftRow(row: TradeDraftRow): TradeDraftValidationIssue[] {
  const issues: TradeDraftValidationIssue[] = []

  if (parseOptionalSignedNumber(row.size) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'size',
      message: 'Size must be a valid number.',
    })
  }

  if (parseCurrencyInput(row.strikePrice, { allowBlank: true }) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'strikePrice',
      message: 'Strike price must be a positive currency value.',
    })
  }

  if (parseCurrencyInput(row.creditDebit, { allowBlank: true }) === 'invalid') {
    issues.push({
      localId: row.localId,
      field: 'creditDebit',
      message: 'Credit/debit must be a positive currency value.',
    })
  }

  if (
    parseCurrencyInput(row.exit, {
      allowBlank: true,
      allowZero: true,
    }) === 'invalid'
  ) {
    issues.push({
      localId: row.localId,
      field: 'exit',
      message: 'Exit must be blank, zero, or a positive currency value.',
    })
  }

  if (row.status !== 'Completed') {
    return issues
  }

  const storedRow = storedRowFromTradeDraft(row, 0)
  if (completedValidTrade(storedRow) === null) {
    issues.push({
      localId: row.localId,
      field: 'row',
      message:
        'Completed rows require strategy, ticker, month, size, strike price, and credit/debit.',
    })
  }

  return issues
}

function parseOptionalSignedNumber(value: string) {
  return parseDecimalInput(value, true)
}

function validSignedNumber(value: string) {
  const parsedValue = parseOptionalSignedNumber(value)
  return parsedValue === 'invalid' ? null : parsedValue
}

function validPositiveCurrency(value: string) {
  const parsedValue = parseCurrencyInput(value, { allowBlank: true })
  return parsedValue === 'invalid' ? null : parsedValue
}

function validExitCurrency(value: string) {
  const parsedValue = parseCurrencyInput(value, {
    allowBlank: true,
    allowZero: true,
  })
  return parsedValue === 'invalid' ? null : parsedValue
}

function normalizeNullableStrategy(value: string) {
  const normalizedValue = normalizeStrategyOption(value)
  return normalizedValue || null
}

function draftNumberText(value: number | null) {
  return value === null ? '' : String(value)
}

function isOptionsTradeMonth(value: string): value is OptionsTradeMonth {
  return OPTIONS_TRADE_MONTHS.includes(value as OptionsTradeMonth)
}

function isFiniteNumber(value: number) {
  return Number.isFinite(value)
}

function numericChartValue(value: number | string) {
  return typeof value === 'number' ? value : 0
}
