import { expect, it } from 'vitest'
import type { NavRow } from '@/api/portfolioNav'
import { availableNavRanges, currencySegments, navPoints, navRangeRows } from './navChart'
const row = (report_date: string, currency = 'USD'): NavRow => ({ account: 'DU1', report_date, currency, nav: '0', source: 'flex', updated_at: '' })
it('uses calendar ranges with month-end clamping without inserting dates', () => {
  const rows = [row('2026-02-27'), row('2026-02-28'), row('2026-03-31')]
  expect(navRangeRows(rows, '1M', new Date('2026-03-31'))).toEqual(rows.slice(1))
  expect(navRangeRows(rows, 'All')).toEqual(rows)
  expect(navRangeRows([row('2025-12-31'), row('2026-01-01')], 'YTD', new Date('2026-09-09'))).toHaveLength(1)
})
it('separates every currency transition, including a return to the first currency', () => {
  expect(currencySegments([row('2026-01-01'), row('2026-01-02','SGD'), row('2026-01-03')])).toHaveLength(3)
})

it('offers long ranges only when history covers them and filters their dates', () => {
  const today = new Date('2026-09-09')
  expect(availableNavRanges([row('2024-01-01')], today)).not.toContain('3Y')
  expect(availableNavRanges([row('2023-09-09')], today)).toContain('3Y')
  expect(availableNavRanges([row('2023-09-09')], today)).not.toContain('5Y')
  expect(availableNavRanges([row('2021-09-09')], today)).toContain('5Y')
  const rows = [row('2021-09-08'), row('2021-09-09'), row('2023-09-09'), row('2026-09-08')]
  expect(navRangeRows(rows, '5Y', today)).toEqual(rows.slice(1))
  expect(navRangeRows(rows, '3Y', today)).toEqual(rows.slice(2))
})

it('rebases percentages to the range start and rejects nonpositive baselines', () => {
  const rows = ['100', '125', '80'].map((nav, i) => ({ ...row(`2026-09-0${i + 1}`), nav }))
  expect(navPoints(rows, true).map(point => Math.round(point.value))).toEqual([0, 25, -20])
  expect(navPoints(rows.slice(1), true).map(point => point.value)).toEqual([0, -36])
  expect(navPoints(rows, false).map(point => point.value)).toEqual([100, 125, 80])
  expect(navPoints([row('2026-09-01')], true)).toEqual([])
  expect(navPoints([{ ...rows[0], nav: '-100' }], true)).toEqual([])
})
