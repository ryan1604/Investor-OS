import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchPortfolioChartValues,
  portfolioChartValuesPath,
  replacePortfolioChartValues,
  type PortfolioChartValuesRequest,
} from '@/api/portfolioChartValues'

const request: PortfolioChartValuesRequest = {
  rows: [
    {
      month: '2026-01',

      amount_invested: 1000,
    },
  ],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('portfolio chart values api', () => {
  it('builds account-scoped chart values paths', () => {
    expect(portfolioChartValuesPath(' du1234567 ')).toBe(
      '/portfolio/chart-values?account=DU1234567',
    )
  })

  it('requires an account before making requests', () => {
    expect(() => portfolioChartValuesPath(' ')).toThrow('Account is required.')
  })

  it('fetches and replaces portfolio chart values for one account', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ account: 'DU1234567', rows: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ account: 'DU1234567', rows: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchPortfolioChartValues('du1234567')
    await replacePortfolioChartValues('du1234567', request)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/portfolio/chart-values?account=DU1234567',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/portfolio/chart-values?account=DU1234567',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal: undefined,
      },
    )
  })

  it('surfaces backend portfolio chart value errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Account is required.' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(fetchPortfolioChartValues('DU1234567')).rejects.toThrow(
      'Account is required.',
    )
  })
})
