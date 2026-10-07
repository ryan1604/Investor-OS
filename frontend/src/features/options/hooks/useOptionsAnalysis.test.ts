// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react'
import type { FormEvent } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchOptionExpirations,
  fetchOptionsAnalysis,
  type OptionExpirationsResponse,
  type OptionsAnalysisResponse,
} from '@/api/options'
import { useOptionsAnalysis } from '@/features/options/hooks/useOptionsAnalysis'

vi.mock('@/api/options', () => ({
  fetchOptionExpirations: vi.fn(),
  fetchOptionsAnalysis: vi.fn(),
}))

afterEach(() => {
  vi.clearAllMocks()
})

describe('useOptionsAnalysis', () => {
  it('ignores an older response after a newer ticker is submitted', async () => {
    const requests: Array<{
      resolve: (analysis: OptionsAnalysisResponse) => void
      signal?: AbortSignal
    }> = []
    vi.mocked(fetchOptionsAnalysis).mockImplementation((_ticker, signal) =>
      new Promise((resolve) => {
        requests.push({ resolve, signal })
      }),
    )
    vi.mocked(fetchOptionExpirations).mockResolvedValue({
      ticker: 'MSFT',
      expirations: [],
      selected_expiration: null,
      message: null,
    })

    const { result } = renderHook(() => useOptionsAnalysis())

    act(() => {
      result.current.setTicker('AAPL')
    })
    act(() => {
      void result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as FormEvent<HTMLFormElement>)
    })
    await waitFor(() => expect(requests).toHaveLength(1))

    act(() => {
      result.current.setTicker('MSFT')
    })
    act(() => {
      void result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as FormEvent<HTMLFormElement>)
    })
    await waitFor(() => expect(requests).toHaveLength(2))

    expect(requests[0].signal?.aborted).toBe(true)

    await act(async () => {
      requests[0].resolve(analysisResponse('AAPL'))
      await Promise.resolve()
    })
    expect(result.current.analysis).toBeNull()

    await act(async () => {
      requests[1].resolve(analysisResponse('MSFT'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(result.current.analysis?.ticker).toBe('MSFT')
    })
  })

  it('aborts an in-flight analysis request on cleanup', async () => {
    const requestSignals: AbortSignal[] = []
    vi.mocked(fetchOptionsAnalysis).mockImplementation((_ticker, signal) => {
      if (signal) {
        requestSignals.push(signal)
      }

      return new Promise<never>(() => undefined)
    })

    const { result, unmount } = renderHook(() => useOptionsAnalysis())

    act(() => {
      result.current.setTicker('AAPL')
    })
    act(() => {
      void result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as FormEvent<HTMLFormElement>)
    })

    await waitFor(() => {
      expect(requestSignals).toHaveLength(1)
    })

    unmount()

    expect(requestSignals[0].aborted).toBe(true)
  })

  it('requests expirations while analysis is loading', async () => {
    let resolveAnalysis: (analysis: OptionsAnalysisResponse) => void = () =>
      undefined
    vi.mocked(fetchOptionsAnalysis).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAnalysis = resolve
        }),
    )
    vi.mocked(fetchOptionExpirations).mockResolvedValue(
      expirationsResponse('AAPL'),
    )

    const { result } = renderHook(() => useOptionsAnalysis())

    submitTicker(result, 'AAPL')
    await waitFor(() => {
      expect(fetchOptionExpirations).toHaveBeenCalledWith(
        'AAPL',
        expect.any(AbortSignal),
      )
    })
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.expirations).toEqual([])
    expect(result.current.isExpirationsLoading).toBe(true)

    await act(async () => {
      resolveAnalysis(analysisResponse('AAPL'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(result.current.selectedExpiration).toBe('2026-06-19')
    })
    expect(result.current.expirations).toHaveLength(2)
    expect(result.current.isExpirationsLoading).toBe(false)
  })

  it('does not show expirations when analysis fails', async () => {
    vi.mocked(fetchOptionsAnalysis).mockRejectedValue(new Error('No data.'))
    vi.mocked(fetchOptionExpirations).mockResolvedValue(
      expirationsResponse('AAPL'),
    )

    const { result } = renderHook(() => useOptionsAnalysis())

    submitTicker(result, 'AAPL')

    await waitFor(() => {
      expect(result.current.error).not.toBeNull()
    })
    expect(result.current.expirations).toEqual([])
    expect(result.current.selectedExpiration).toBe('')
    expect(result.current.isExpirationsLoading).toBe(false)
  })

  it('ignores expirations from an older ticker', async () => {
    const expirationRequests: Array<
      (response: OptionExpirationsResponse) => void
    > = []
    vi.mocked(fetchOptionsAnalysis).mockImplementation((ticker) =>
      Promise.resolve(analysisResponse(ticker)),
    )
    vi.mocked(fetchOptionExpirations).mockImplementation(
      () =>
        new Promise((resolve) => {
          expirationRequests.push(resolve)
        }),
    )

    const { result } = renderHook(() => useOptionsAnalysis())

    submitTicker(result, 'AAPL')
    await waitFor(() => expect(expirationRequests).toHaveLength(1))
    submitTicker(result, 'MSFT')
    await waitFor(() => expect(expirationRequests).toHaveLength(2))

    await act(async () => {
      expirationRequests[0](expirationsResponse('AAPL', '2026-07-17'))
      expirationRequests[1](expirationsResponse('MSFT'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(result.current.analysis?.ticker).toBe('MSFT')
      expect(result.current.selectedExpiration).toBe('2026-06-19')
    })
  })
})

function submitTicker(
  result: { current: ReturnType<typeof useOptionsAnalysis> },
  ticker: string,
) {
  act(() => {
    result.current.setTicker(ticker)
  })
  act(() => {
    void result.current.handleSubmit({
      preventDefault: vi.fn(),
    } as unknown as FormEvent<HTMLFormElement>)
  })
}

function expirationsResponse(
  ticker: string,
  firstExpiration = '2026-06-19',
): OptionExpirationsResponse {
  return {
    ticker,
    expirations: [
      { date: firstExpiration, days_to_expiration: 20 },
      { date: '2026-08-21', days_to_expiration: 83 },
    ],
    selected_expiration: firstExpiration,
    message: null,
  }
}

function analysisResponse(ticker: string): OptionsAnalysisResponse {
  return {
    ticker,
    underlying_price: 100,
    candles: [],
    bollinger_bands: [],
    rsi: [],
    message: null,
  }
}
