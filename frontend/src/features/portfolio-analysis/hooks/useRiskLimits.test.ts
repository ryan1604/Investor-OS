// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useRiskLimits } from '@/features/portfolio-analysis/hooks/useRiskLimits'

function limitsResponse(account: string, value: number) {
  return new Response(
    JSON.stringify({
      account,
      limits: [{ key: 'margin_utilisation_percent', value, updated_at: '2026-09-26T00:00:00Z' }],
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('useRiskLimits', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads limits per account and never shows another account’s limits', async () => {
    let resolveDu2: (response: Response) => void = () => {}
    const fetchMock = vi.fn((url: string) =>
      url.endsWith('/DU1')
        ? Promise.resolve(limitsResponse('DU1', 30))
        : new Promise<Response>((resolve) => {
            resolveDu2 = resolve
          }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(({ account }) => useRiskLimits(account), {
      initialProps: { account: 'DU1' as string | null },
    })
    await waitFor(() => expect(result.current.isLoaded).toBe(true))
    expect(result.current.limits.map((limit) => limit.value)).toEqual([30])

    rerender({ account: 'DU2' })
    expect(result.current.isLoaded).toBe(false)
    expect(result.current.limits).toEqual([])

    act(() => resolveDu2(limitsResponse('DU2', 40)))
    await waitFor(() => expect(result.current.limits.map((limit) => limit.value)).toEqual([40]))
  })

  it('ignores a save that finishes after switching accounts', async () => {
    let resolveSave: (response: Response) => void = () => {}
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        return new Promise<Response>((resolve) => {
          resolveSave = resolve
        })
      }
      return Promise.resolve(limitsResponse(url.endsWith('/DU1') ? 'DU1' : 'DU2', 40))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(({ account }) => useRiskLimits(account), {
      initialProps: { account: 'DU1' as string | null },
    })
    await waitFor(() => expect(result.current.isLoaded).toBe(true))

    let saving: Promise<boolean> = Promise.resolve(false)
    act(() => {
      saving = result.current.save({ margin_utilisation_percent: 20 })
    })
    rerender({ account: 'DU2' })
    await waitFor(() => expect(result.current.isLoaded).toBe(true))

    await act(async () => {
      resolveSave(limitsResponse('DU1', 20))
      expect(await saving).toBe(true)
    })
    expect(result.current.isLoaded).toBe(true)
    expect(result.current.limits.map((limit) => limit.value)).toEqual([40])
    expect(result.current.isSaving).toBe(false)
  })

  it('saves limits and reports failures', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(limitsResponse('DU1', 30))
      .mockResolvedValueOnce(limitsResponse('DU1', 20))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'Bad limits' }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useRiskLimits('DU1'))
    await waitFor(() => expect(result.current.isLoaded).toBe(true))

    let saved = false
    await act(async () => {
      saved = await result.current.save({ margin_utilisation_percent: 20 })
    })
    expect(saved).toBe(true)
    expect(result.current.limits.map((limit) => limit.value)).toEqual([20])
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/portfolio/analysis/limits/DU1',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ limits: { margin_utilisation_percent: 20 } }),
      }),
    )

    await act(async () => {
      saved = await result.current.save({ margin_utilisation_percent: 10 })
    })
    expect(saved).toBe(false)
    expect(result.current.error).toBeTruthy()
    expect(result.current.limits.map((limit) => limit.value)).toEqual([20])
  })
})
