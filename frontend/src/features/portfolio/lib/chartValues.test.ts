import { describe, expect, it } from 'vitest'

import {
  formatCompactCurrency,
  formatFullMonthLabel,
  formatMonthLabel,
  formatTooltipCurrency,
  normalizePortfolioChartValues,
  toSimpleYearChartRows,
  validatePortfolioChartValueRows,
  type PortfolioChartValueInput,
} from '@/features/portfolio/lib/chartValues'

const rows: PortfolioChartValueInput[] = [
  {
    month: '2026-03',
    portfolio_value: 1300,
    amount_invested: null,
  },
  {
    month: '2026-01',
    portfolio_value: null,
    amount_invested: 1000,
  },
  {
    month: '2026-02',
    portfolio_value: 1200,
    amount_invested: 950,
  },
]

describe('portfolio chart value helpers', () => {
  it('labels months as MMM YY while sorting by month keys', () => {
    const chartRows = normalizePortfolioChartValues(rows)

    expect(chartRows.map((row) => row.month)).toEqual([
      '2026-01',
      '2026-02',
      '2026-03',
    ])
    expect(chartRows.map((row) => row.label)).toEqual([
      'Jan 26',
      'Feb 26',
      'Mar 26',
    ])
  })

  it('preserves partial metric rows for advanced charts', () => {
    const chartRows = normalizePortfolioChartValues(rows)

    expect(chartRows[0]).toMatchObject({
      portfolio_value: null,
      amount_invested: 1000,
    })
    expect(chartRows[2]).toMatchObject({
      portfolio_value: 1300,
      amount_invested: null,
    })
  })

  it('derives simple yearly rows from usable December values only', () => {
    const simpleRows = toSimpleYearChartRows([
      { month: '2024-12', portfolio_value: 900, amount_invested: null },
      { month: '2025-11', portfolio_value: 1000, amount_invested: 900 },
      { month: '2025-12', portfolio_value: null, amount_invested: 1100 },
      { month: '2026-12', portfolio_value: null, amount_invested: null },
    ])

    expect(simpleRows).toEqual([
      {
        month: '2024-12',
        portfolio_value: 900,
        amount_invested: null,
        year: '2024',
        label: 'Dec 2024',
      },
      {
        month: '2025-12',
        portfolio_value: null,
        amount_invested: 1100,
        year: '2025',
        label: 'Dec 2025',
      },
    ])
  })

  it('formats month and currency labels for charts', () => {
    expect(formatMonthLabel('2025-01')).toBe('Jan 25')
    expect(formatFullMonthLabel('2025-12')).toBe('Dec 2025')
    expect(formatCompactCurrency(1250000)).toBe('$1.3M')
    expect(formatTooltipCurrency(1250.5)).toBe('$1,250.50')
    expect(formatCompactCurrency(null)).toBe('-')
    expect(formatTooltipCurrency(null)).toBe('-')
  })

  it('validates missing, duplicate, invalid, and blank rows', () => {
    const issues = validatePortfolioChartValueRows([
      { month: '', portfolio_value: '1000' },
      { month: '2026-13', portfolio_value: '1000' },
      { month: '2026-02', portfolio_value: 'nope' },
      { month: '2026-02', amount_invested: '900' },
      { month: '2026-03', portfolio_value: '', amount_invested: null },
    ])

    expect(issues).toEqual([
      { index: 0, field: 'month', message: 'Month is required.' },
      {
        index: 1,
        field: 'month',
        message: 'Month must use YYYY-MM format.',
      },
      {
        index: 2,
        field: 'portfolio_value',
        message: 'Portfolio value must be a valid number.',
      },
      {
        index: 4,
        field: 'row',
        message: 'Portfolio value or amount invested is required.',
      },
      { index: 2, field: 'month', message: 'Month must be unique.' },
      { index: 3, field: 'month', message: 'Month must be unique.' },
    ])
  })
})
