// @vitest-environment jsdom

import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  OptionChainResponse,
  OptionsAnalysisResponse,
} from '@/api/options'
import { useOptionChain } from '@/features/options/hooks/useOptionChain'

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []

  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor() {
    FakeWebSocket.sockets.push(this)
  }

  close() {
    this.closed = true
  }
}

const analysis: OptionsAnalysisResponse = {
  ticker: 'AAPL',
  underlying_price: 100,
  candles: [
    {
      date: '2026-05-30',
      open: 99,
      high: 101,
      low: 98,
      close: 100,
      volume: 1_000,
    },
  ],
  bollinger_bands: [],
  rsi: [],
  message: null,
}

const chain: OptionChainResponse = {
  ticker: 'AAPL',
  expiration: '2026-06-19',
  underlying_price: 100,
  rows: [],
  message: null,
}

describe('useOptionChain', () => {
  beforeEach(() => {
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => chain,
      })),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not restart transports when a live chart update replaces analysis', async () => {
    const { rerender, unmount } = renderHook(
      ({ currentAnalysis }) =>
        useOptionChain(currentAnalysis, '2026-06-19', false),
      { initialProps: { currentAnalysis: analysis } },
    )

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1)
    })
    expect(FakeWebSocket.sockets).toHaveLength(1)

    rerender({
      currentAnalysis: {
        ...analysis,
        underlying_price: 103,
        candles: [{ ...analysis.candles[0], close: 103 }],
      },
    })

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(FakeWebSocket.sockets).toHaveLength(1)

    unmount()
    expect(FakeWebSocket.sockets[0].closed).toBe(true)
  })
})
