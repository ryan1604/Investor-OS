// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { usePortfolioChartValues } from '@/features/portfolio/hooks/usePortfolioChartValues'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('usePortfolioChartValues', () => {
  it('loads chart values when the selected account changes', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            account: 'DU1234567',
            rows: [{ month: '2026-01', portfolio_value: 1000 }],
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            account: 'DU7654321',
            rows: [{ month: '2026-02', amount_invested: 900 }],
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ account }) => usePortfolioChartValues(account),
      { initialProps: { account: 'DU1234567' as string | undefined } },
    )

    await waitFor(() => {
      expect(result.current.rows[0]?.month).toBe('2026-01')
    })

    rerender({ account: 'DU7654321' })

    await waitFor(() => {
      expect(result.current.rows[0]?.month).toBe('2026-02')
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/portfolio/chart-values?account=DU1234567',
      { signal: expect.any(AbortSignal) },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/portfolio/chart-values?account=DU7654321',
      { signal: expect.any(AbortSignal) },
    )
  })

  it('clears rows when there is no selected account', () => {
    const { result } = renderHook(() => usePortfolioChartValues(undefined))

    act(() => undefined)

    expect(result.current.rows).toEqual([])
    expect(result.current.error).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('saves the replacement set for the selected account', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ account: 'DU1234567', rows: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            account: 'DU1234567',
            rows: [
              {
                month: '2026-01',
                portfolio_value: 1000,
                amount_invested: null,
                updated_at: '2026-06-06T00:00:00+00:00',
              },
            ],
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => usePortfolioChartValues('DU1234567'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      await result.current.saveRows([
        {
          month: '2026-01',
          portfolio_value: 1000,
          amount_invested: null,
        },
      ])
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/portfolio/chart-values?account=DU1234567',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rows: [
            {
              month: '2026-01',
              portfolio_value: 1000,
              amount_invested: null,
            },
          ],
        }),
        signal: undefined,
      },
    )
    expect(result.current.rows[0]?.month).toBe('2026-01')
  })
})
