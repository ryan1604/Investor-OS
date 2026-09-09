import { expect, it } from 'vitest'
import { parsePortfolioChartValueDraftRows, validatePortfolioChartValueRows, formatMonthLabel } from './chartValues'
it('parses and sorts monthly amounts, preserving zero', () => {
  expect(parsePortfolioChartValueDraftRows([
    { month: '2026-02', amount_invested: '0' },
    { month: '2026-01', amount_invested: '1000.25' },
  ])).toEqual([{ month: '2026-01', amount_invested: 1000.25 }, { month: '2026-02', amount_invested: 0 }])
  expect(formatMonthLabel('2026-01')).toBe('Jan 26')
})
it('rejects duplicate months, malformed months, nonfinite and blank amounts', () => {
  for (const rows of [
    [{ month: '2026-13', amount_invested: '1' }],
    [{ month: '2026-01', amount_invested: '' }],
    [{ month: '2026-01', amount_invested: 'Infinity' }],
    [{ month: '2026-01', amount_invested: '1' }, { month: '2026-01', amount_invested: '2' }],
  ]) expect(validatePortfolioChartValueRows(rows).length).toBeGreaterThan(0)
})
