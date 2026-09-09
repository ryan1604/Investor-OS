// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react'
import type { FormEvent } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchOptionExpirations,
  fetchOptionsAnalysis,
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
})

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
