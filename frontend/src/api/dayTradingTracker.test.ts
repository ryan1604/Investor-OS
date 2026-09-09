import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  dayTradingDateTradesPath,
  dayTradingMonthPath,
  fetchDayTradingMonth,
  replaceDayTradingDateTrades,
} from '@/api/dayTradingTracker'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('day trading tracker api', () => {
  it('builds month and date paths', () => {
    expect(dayTradingMonthPath('2026-08')).toBe(
      '/day-trading-tracker/months/2026-08',
    )
    expect(dayTradingDateTradesPath('2026-08-20')).toBe(
      '/day-trading-tracker/days/2026-08-20/trades',
    )
  })

  it('fetches months and replaces date trades', async () => {
    const request = {
      trades: [
        {
          id: 'row-1',
          display_order: 1,
          buy: 10,
          sell: 11,
          size: 2,
          fee: 1.5,
        },
      ],
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ month: '2026-08', days: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ date: '2026-08-20', trades: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchDayTradingMonth('2026-08')
    await replaceDayTradingDateTrades('2026-08-20', request)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/day-trading-tracker/months/2026-08',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/day-trading-tracker/days/2026-08-20/trades',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal: undefined,
      },
    )
  })
})
