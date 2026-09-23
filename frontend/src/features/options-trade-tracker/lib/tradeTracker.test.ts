import { describe, expect, it } from 'vitest'

import {
  calculateTradesFooterTotal,
  deriveNetMonthlyChartData,
  deriveStackedMonthlyChartData,
  deriveStrategyCountPieData,
  deriveStrategyStats,
  formatAverage,
  formatCurrencyInput,
  normalizeStrategyOption,
  parseCurrencyInput,
  projectCompletedValidTrades,
  type StrategyStatsTable,
} from '@/features/options-trade-tracker/lib/tradeTracker'
import type { OptionsTradeRow } from '@/api/optionsTradeTrackers'

const completedWheelTrade: OptionsTradeRow = {
  id: 'row-1',
  display_order: 1,
  status: 'Completed',
  strategy: 'WHEEL',
  ticker: 'AAPL',
  month: 'jan',
  expiry_date: null,
  size: -2,
  strike_price: 190,
  credit_debit: 1.5,
  exit: null,
  created_at: '',
  updated_at: '',
}

const completedSpreadTrade: OptionsTradeRow = {
  id: 'row-2',
  display_order: 2,
  status: 'Completed',
  strategy: 'SPREAD',
  ticker: 'MSFT',
  month: 'feb',
  expiry_date: null,
  size: 1,
  strike_price: 420,
  credit_debit: 2,
  exit: 0.5,
  created_at: '',
  updated_at: '',
}

const inProgressTrade: OptionsTradeRow = {
  id: 'row-3',
  display_order: 3,
  status: 'In Progress',
  strategy: 'WHEEL',
  ticker: 'TSLA',
  month: 'mar',
  expiry_date: null,
  size: -1,
  strike_price: 200,
  credit_debit: 1,
  exit: 0,
  created_at: '',
  updated_at: '',
}

describe('options trade tracker helpers', () => {
  it('normalizes strategy options', () => {
    expect(normalizeStrategyOption(' iron   condor ')).toBe('IRON CONDOR')
    expect(normalizeStrategyOption(' wheel ')).toBe('WHEEL')
  })

  it('parses and formats currency values as raw decimals', () => {
    expect(parseCurrencyInput('1.25')).toBe(1.25)
    expect(parseCurrencyInput(2)).toBe(2)
    expect(parseCurrencyInput('')).toBe('invalid')
    expect(parseCurrencyInput('-1')).toBe('invalid')
    expect(parseCurrencyInput('0')).toBe('invalid')
    expect(parseCurrencyInput('0', { allowZero: true })).toBe(0)
    expect(parseCurrencyInput('', { allowBlank: true, allowZero: true })).toBeNull()
    expect(formatCurrencyInput(1.25)).toBe('$1.25')
    expect(formatCurrencyInput(null)).toBe('')
  })

  it('projects only completed valid rows and treats blank exit as zero', () => {
    expect(
      projectCompletedValidTrades([
        completedWheelTrade,
        completedSpreadTrade,
        inProgressTrade,
        { ...completedWheelTrade, ticker: null },
        { ...completedWheelTrade, credit_debit: -1 },
        { ...completedWheelTrade, size: 0 },
      ]),
    ).toEqual([
      { row: completedWheelTrade, pnl: 296 },
      { row: completedSpreadTrade, pnl: -148 },
    ])
  })

  it('derives footer total from completed rows with computed P&L', () => {
    expect(
      calculateTradesFooterTotal(
        projectCompletedValidTrades([
          completedWheelTrade,
          completedSpreadTrade,
          inProgressTrade,
        ]),
      ),
    ).toBe(148)
  })

  it('includes all global strategies and aggregates completed valid trades only', () => {
    const stats = deriveStrategyStats(
      projectCompletedValidTrades([
          completedWheelTrade,
          completedSpreadTrade,
          inProgressTrade,
          { ...completedWheelTrade, id: 'row-4', month: 'jan', size: -1 },
          { ...completedWheelTrade, id: 'row-zero', size: 0 },
        ]),
      ['WHEEL', 'SPREAD', 'IRON CONDOR'],
    )
    const rowsByStrategy = new Map(
      stats.rows.map((row) => [row.strategy, row] as const),
    )

    expect(strategyRow(rowsByStrategy, 'WHEEL')).toMatchObject({
      total: 444,
      count: 3,
      average: 148,
    })
    expect(strategyRow(rowsByStrategy, 'WHEEL').months.jan).toBe(444)
    expect(strategyRow(rowsByStrategy, 'SPREAD')).toMatchObject({
      total: -148,
      count: 1,
      average: -148,
    })
    expect(strategyRow(rowsByStrategy, 'IRON CONDOR')).toMatchObject({
      total: 0,
      count: 0,
      average: null,
    })
    expect(stats.monthTotals.jan).toBe(444)
    expect(stats.monthTotals.feb).toBe(-148)
    expect(stats.total).toBe(296)
    expect(stats.count).toBe(4)
    expect(stats.average).toBe(74)
    expect(formatAverage(strategyRow(rowsByStrategy, 'IRON CONDOR').average)).toBe(
      '-',
    )
  })

  it('derives stacked monthly, net monthly, and strategy-count pie chart data', () => {
    const rows: OptionsTradeRow[] = [
      completedWheelTrade,
      completedSpreadTrade,
      { ...completedWheelTrade, id: 'row-4', month: 'feb', size: -1 },
      inProgressTrade,
    ]
    const completedTrades = projectCompletedValidTrades(rows)
    const stackedRows = deriveStackedMonthlyChartData(completedTrades, [
      'WHEEL',
      'SPREAD',
      'IRON CONDOR',
    ])
    const netRows = deriveNetMonthlyChartData(completedTrades)
    const pieSlices = deriveStrategyCountPieData(completedTrades)

    expect(stackedRows[0]).toMatchObject({
      month: 'jan',
      label: 'Jan',
      WHEEL: 296,
      SPREAD: 0,
      'IRON CONDOR': 0,
    })
    expect(stackedRows[1]).toMatchObject({
      month: 'feb',
      WHEEL: 148,
      SPREAD: -148,
      'IRON CONDOR': 0,
    })
    expect(netRows[0]).toMatchObject({ month: 'jan', total: 296 })
    expect(netRows[1]).toMatchObject({ month: 'feb', total: 0 })
    expect(pieSlices).toEqual([
      { strategy: 'SPREAD', count: 1 },
      { strategy: 'WHEEL', count: 3 },
    ])
  })

  it('keeps signed monthly strategy contributions reconciled with the summary and Net P&L', () => {
    const strategies = ['CC', 'CSP', 'CUSTOM / RATIO SPREAD']
    const values: [OptionsTradeRow['month'], string, number][] = [
      ['may', 'CC', 1500], ['may', 'CC', -300],
      ['may', 'CSP', -400], ['may', 'CUSTOM / RATIO SPREAD', 1200],
      ['jun', 'CC', -1200], ['jun', 'CSP', -400], ['jun', 'CUSTOM / RATIO SPREAD', -1200],
      ['jul', 'CC', 1200], ['jul', 'CSP', 400], ['jul', 'CUSTOM / RATIO SPREAD', 1200],
      ['aug', 'CC', 1200], ['aug', 'CSP', -1200],
      ['sep', 'CC', 0],
    ]
    const completedTrades = projectCompletedValidTrades(values.map(([month, strategy, pnl], index) => ({
      ...completedWheelTrade, id: `signed-${index}`, month, strategy,
      size: pnl < 0 ? 1 : -1, credit_debit: (Math.abs(pnl) + 2) / 100, exit: 0,
    })))
    const stats = deriveStrategyStats(completedTrades, strategies)
    const stacked = deriveStackedMonthlyChartData(completedTrades, strategies)
    const net = deriveNetMonthlyChartData(completedTrades)

    expect(stacked[4].CC).toBeCloseTo(1200)
    expect(stacked[4].CSP).toBeCloseTo(-400)
    expect(stacked[4]['CUSTOM / RATIO SPREAD']).toBeCloseTo(1200)
    const expectedTotals = [2000, -2800, 2800, 0, 0]
    expectedTotals.forEach((total, index) => expect(net[index + 4].total).toBeCloseTo(total))
    for (const [index, month] of net.entries()) {
      const contributions = stats.rows.map((row) => row.months[month.month])
      stats.rows.forEach((row) => expect(stacked[index][row.strategy]).toBe(row.months[month.month]))
      const positive = contributions.filter((value) => value > 0).reduce((sum, value) => sum + value, 0)
      const negative = contributions.filter((value) => value < 0).reduce((sum, value) => sum + value, 0)
      expect(positive + negative).toBeCloseTo(month.total)
      expect(month.total).toBe(stats.monthTotals[month.month])
    }
    expect(net[0]).toMatchObject({ month: 'jan', total: 0 })
  })
})

function strategyRow(
  rowsByStrategy: Map<string, StrategyStatsTable['rows'][number]>,
  strategy: string,
) {
  const row = rowsByStrategy.get(strategy)

  if (row === undefined) {
    throw new Error(`Expected ${strategy} row.`)
  }

  return row
}
