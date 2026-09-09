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
            rows: [{ month: '2026-01', amount_invested: 1000 }],
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

  it('does not expose or apply rows from a previous account', async () => {
    const firstLoad = deferred<Response>()
    const secondLoad = deferred<Response>()
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(firstLoad.promise)
      .mockReturnValueOnce(secondLoad.promise)
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ account }) => usePortfolioChartValues(account),
      { initialProps: { account: 'ACCOUNT-A' as string | undefined } },
    )

    rerender({ account: 'ACCOUNT-B' })

    expect(result.current.rows).toEqual([])
    expect(result.current.isLoading).toBe(true)
    expect(
      (fetchMock.mock.calls[0][1] as { signal: AbortSignal }).signal.aborted,
    ).toBe(true)

    secondLoad.resolve(chartValuesResponse('ACCOUNT-B', '2026-02', 2_000))
    await waitFor(() => {
      expect(result.current.rows[0]?.amount_invested).toBe(2_000)
    })

    firstLoad.resolve(chartValuesResponse('ACCOUNT-A', '2026-01', 1_000))
    await act(async () => {
      await firstLoad.promise
    })

    expect(result.current.rows[0]?.amount_invested).toBe(2_000)
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

                amount_invested: 1000,
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

          amount_invested: 1000,
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

              amount_invested: 1000,
            },
          ],
        }),
        signal: expect.any(AbortSignal),
      },
    )
    expect(result.current.rows[0]?.month).toBe('2026-01')
  })

  it('ignores a late save response after the account changes', async () => {
    const saveResponse = deferred<Response>()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(chartValuesResponse('ACCOUNT-A', '2026-01', 1_000))
      .mockReturnValueOnce(saveResponse.promise)
      .mockResolvedValueOnce(chartValuesResponse('ACCOUNT-B', '2026-02', 2_000))
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ account }) => usePortfolioChartValues(account),
      { initialProps: { account: 'ACCOUNT-A' as string | undefined } },
    )
    await waitFor(() => {
      expect(result.current.rows[0]?.amount_invested).toBe(1_000)
    })

    let pendingSave: Promise<unknown>
    act(() => {
      pendingSave = result.current.saveRows([
        { month: '2026-01', amount_invested: 1_500 },
      ])
    })
    rerender({ account: 'ACCOUNT-B' })

    await waitFor(() => {
      expect(result.current.rows[0]?.amount_invested).toBe(2_000)
    })
    expect(
      (fetchMock.mock.calls[1][1] as { signal: AbortSignal }).signal.aborted,
    ).toBe(true)

    saveResponse.resolve(chartValuesResponse('ACCOUNT-A', '2026-01', 1_500))
    await act(async () => {
      await pendingSave
    })

    expect(result.current.rows[0]?.amount_invested).toBe(2_000)
    expect(result.current.isSaving).toBe(false)
  })
})

function chartValuesResponse(account: string, month: string, value: number) {
  return new Response(
    JSON.stringify({
      account,
      rows: [
        {
          month,

          amount_invested: value,
          updated_at: '2026-06-06T00:00:00+00:00',
        },
      ],
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    },
  )
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}
