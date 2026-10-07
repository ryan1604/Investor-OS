import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deleteBetaOverride,
  fetchBetaOverrides,
  portfolioAnalysisWebSocketUrl,
  saveBetaOverride,
} from '@/api/portfolioAnalysis'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('portfolio analysis api', () => {
  it('calls the beta override endpoints', async () => {
    const override = { ticker: 'HIMS', beta: 1.8, updated_at: '2026-09-26T00:00:00Z' }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([override]))
      .mockResolvedValueOnce(jsonResponse(override))
      .mockResolvedValueOnce(jsonResponse(null, 204))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchBetaOverrides()).resolves.toEqual([override])
    await expect(saveBetaOverride(' hims ', 1.8)).resolves.toEqual(override)
    await deleteBetaOverride('hims')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/portfolio/analysis/beta-overrides',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/portfolio/analysis/beta-overrides/HIMS',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ beta: 1.8 }),
        signal: undefined,
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/portfolio/analysis/beta-overrides/HIMS',
      { method: 'DELETE' },
    )
  })

  it('surfaces the server error for a missing override', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'Beta override not found.' }, 404)),
    )

    await expect(deleteBetaOverride('AAPL')).rejects.toThrow('Beta override not found.')
  })

  it('builds the WebSocket URL with the account', () => {
    expect(portfolioAnalysisWebSocketUrl('DU 1')).toBe(
      'ws://127.0.0.1:8000/portfolio/analysis/ws?account=DU%201',
    )
    expect(portfolioAnalysisWebSocketUrl(null)).toBe(
      'ws://127.0.0.1:8000/portfolio/analysis/ws',
    )
  })
})
