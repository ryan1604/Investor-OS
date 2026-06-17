import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelOptionsScreenerScan,
  fetchOptionsScreenerScanState,
  fetchOptionsScreenerSettings,
  getOptionsScreenerScansWsUrl,
  refreshOptionsScreenerQuote,
  replaceOptionsScreenerTickerList,
  saveOptionsScreenerFilters,
  startOptionsScreenerScan,
  type OptionsScreenerFilters,
} from '@/api/optionsScreeners'

const filters: OptionsScreenerFilters = {
  version: 1,
  minimum_dte: 7,
  maximum_dte: 45,
  minimum_absolute_delta: 0.15,
  maximum_absolute_delta: 0.3,
  minimum_annualized_return: 10,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('options screeners api', () => {
  it('fetches settings and sends focused ticker and filter updates', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => {
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    await fetchOptionsScreenerSettings()
    await replaceOptionsScreenerTickerList('csp_cc', ['AAPL', 'MSFT'])
    await saveOptionsScreenerFilters('csp', filters)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/options-screeners/settings',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/options-screeners/settings/ticker-lists/csp_cc',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: ['AAPL', 'MSFT'] }),
        signal: undefined,
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/options-screeners/settings/filters/csp',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(filters),
        signal: undefined,
      },
    )
  })

  it('surfaces backend settings errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Invalid ticker.' }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(
      replaceOptionsScreenerTickerList('cs', ['BAD/TICKER']),
    ).rejects.toThrow('Invalid ticker.')
  })

  it('supports scan recovery, lifecycle, and quote refresh', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => {
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    const quoteRequest = {
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 100,
      right: 'PUT' as const,
      contract: { con_id: 123, local_symbol: 'AAPL PUT' },
    }

    await fetchOptionsScreenerScanState()
    await startOptionsScreenerScan('csp')
    await cancelOptionsScreenerScan('job/1')
    await refreshOptionsScreenerQuote(quoteRequest)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/options-screeners/state',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/options-screeners/scans/csp',
      { method: 'POST', signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/options-screeners/scans/job%2F1/cancel',
      { method: 'POST', signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      'http://127.0.0.1:8000/options-screeners/quotes/refresh',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(quoteRequest),
        signal: undefined,
      },
    )
    expect(getOptionsScreenerScansWsUrl()).toBe(
      'ws://127.0.0.1:8000/options-screeners/scans/ws',
    )
  })

  it('surfaces structured scan conflict messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              message: 'Scan active-id for csp is already active.',
              active_job_id: 'active-id',
              active_screener: 'csp',
            },
          }),
          {
            status: 409,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    await expect(startOptionsScreenerScan('cc')).rejects.toThrow(
      'Scan active-id for csp is already active.',
    )
  })
})
