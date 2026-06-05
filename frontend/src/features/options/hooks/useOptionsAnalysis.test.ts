// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react'
import type { FormEvent } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchOptionsAnalysis } from '@/api/options'
import { useOptionsAnalysis } from '@/features/options/hooks/useOptionsAnalysis'

vi.mock('@/api/options', () => ({
  fetchOptionExpirations: vi.fn(),
  fetchOptionsAnalysis: vi.fn(),
}))

afterEach(() => {
  vi.clearAllMocks()
})

describe('useOptionsAnalysis', () => {
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
