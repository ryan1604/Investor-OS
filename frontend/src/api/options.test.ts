import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchOptionExpirations,
  getOptionChainWsUrl,
} from '@/api/options'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('options api', () => {
  it('fetches option expirations with encoded ticker paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ expirations: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchOptionExpirations('brk b')

    expect(fetchMock).toHaveBeenCalledWith(
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
