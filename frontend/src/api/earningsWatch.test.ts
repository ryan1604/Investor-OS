import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addEarningsWatchTickers,
  clearEarningsWatchReviews,
  fetchEarningsWatch,
  removeEarningsWatchTicker,
  setEarningsWatchReviewed,
} from '@/api/earningsWatch'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('earnings watch api', () => {
  it('calls earnings watch endpoints with expected payloads', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ rows: [], refresh: { state: 'succeeded' } }),
            {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            },
          ),
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchEarningsWatch()
    await addEarningsWatchTickers('aapl msft')
    await removeEarningsWatchTicker(' aapl ')
    await setEarningsWatchReviewed('msft', true)
    await clearEarningsWatchReviews()

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/earnings-watch',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/earnings-watch/tickers',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: 'aapl msft' }),
        signal: undefined,
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/earnings-watch/tickers/AAPL',
      { method: 'DELETE', signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      'http://127.0.0.1:8000/earnings-watch/tickers/MSFT/reviewed',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewed: true }),
        signal: undefined,
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      'http://127.0.0.1:8000/earnings-watch/reviews/clear',
      { method: 'POST', signal: undefined },
    )
  })

  it('surfaces backend errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Ticker not found.' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(removeEarningsWatchTicker('AAPL')).rejects.toThrow(
      'Ticker not found.',
    )
  })
})
