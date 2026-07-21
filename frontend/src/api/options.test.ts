import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchOptionChain,
  fetchOptionExpirations,
  getOptionChainWsUrl,
} from '@/api/options'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('options api', () => {
  it('fetches option chain and expirations with encoded ticker paths', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ rows: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ expirations: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchOptionChain('brk b', '2026-06-19')
    await fetchOptionExpirations('brk b')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/options/BRK%20B/chain?expiration=2026-06-19',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/options/BRK%20B/expirations',
      { signal: undefined },
    )
  })

  it('exports the option chain websocket url', () => {
    expect(getOptionChainWsUrl('brk b', '2026-06-19')).toBe(
      'ws://127.0.0.1:8000/options/BRK%20B/chain/ws?expiration=2026-06-19',
    )
  })
})
