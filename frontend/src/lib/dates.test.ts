import { afterEach, expect, it, vi } from 'vitest'

import { daysToExpiration, isoDate, newYorkDateParts } from '@/lib/dates'
import { millisecondsUntilNextNewYorkMidnight } from '@/features/earnings-watch/lib/earningsWatch'

afterEach(() => vi.useRealTimers())

it('formats local calendar dates without a UTC conversion', () => {
  expect(isoDate(new Date(2026, 0, 2, 23, 30))).toBe('2026-01-02')
})

it('extracts New York dates across midnight and daylight-saving transitions', () => {
  for (const [timestamp, expected] of [
    ['2026-07-02T02:00:00Z', ['2026', '07', '01']],
    ['2026-03-08T04:30:00Z', ['2026', '03', '07']],
    ['2026-03-08T07:30:00Z', ['2026', '03', '08']],
    ['2026-11-01T05:30:00Z', ['2026', '11', '01']],
    ['2026-11-01T06:30:00Z', ['2026', '11', '01']],
  ] as const) {
    const { year, month, day } = newYorkDateParts(new Date(timestamp))
    expect([year, month, day]).toEqual(expected)
  }
})

it('uses the New York calendar date for expiry days and keeps invalid dates invalid', () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-07-02T02:00:00Z'))
  expect(daysToExpiration('2026-07-01')).toBe(0)
  expect(daysToExpiration('2026-07-02')).toBe(1)
  expect(daysToExpiration('2026-06-30')).toBe(-1)
  expect(daysToExpiration('invalid')).toBeNaN()
})

it('keeps the 23-hour and 25-hour midnight delays and the one-minute minimum', () => {
  expect(millisecondsUntilNextNewYorkMidnight(new Date('2026-03-08T05:00:00Z')))
    .toBe(23 * 60 * 60 * 1000)
  expect(millisecondsUntilNextNewYorkMidnight(new Date('2026-11-01T04:00:00Z')))
    .toBe(25 * 60 * 60 * 1000)
  expect(millisecondsUntilNextNewYorkMidnight(new Date('2026-07-02T03:59:59Z')))
    .toBe(60_000)
})
