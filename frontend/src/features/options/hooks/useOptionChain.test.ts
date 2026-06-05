// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  OptionChainResponse,
  OptionQuote,
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

  receive(data: unknown) {
    this.onmessage?.(
      new MessageEvent('message', { data: JSON.stringify(data) }),
    )
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

function quote(overrides: Partial<OptionQuote>): OptionQuote {
  return {
    local_symbol: null,
    delta: null,
    bid: null,
    bid_size: null,
    ask: null,
    ask_size: null,
    mid: null,
    last: null,
    close: null,
    model_price: null,
    change_percent: null,
    volume: null,
    open_interest: null,
    gamma: null,
    theta: null,
    implied_volatility_percent: null,
    breakeven: null,
    ...overrides,
  }
}

describe('useOptionChain', () => {
  let animationFrameCallbacks: FrameRequestCallback[] = []

  beforeEach(() => {
    FakeWebSocket.sockets = []
    animationFrameCallbacks = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn((callback: FrameRequestCallback) => {
        animationFrameCallbacks.push(callback)
        return animationFrameCallbacks.length
      }),
    )
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
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

  it('batches live row updates until the next animation frame', async () => {
    const chainWithRows: OptionChainResponse = {
      ...chain,
      rows: [
        { strike: 100, call: null, put: null },
        { strike: 105, call: null, put: null },
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => chainWithRows,
      })),
    )

    const { result } = renderHook(() =>
      useOptionChain(analysis, '2026-06-19', false),
    )

    await waitFor(() => {
      expect(result.current.chain?.rows).toHaveLength(2)
    })

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        row: {
          strike: 100,
          call: quote({ local_symbol: 'AAPL 100C', bid: 1 }),
          put: null,
        },
      })
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        row: {
          strike: 105,
          call: null,
          put: quote({ local_symbol: 'AAPL 105P', bid: 2 }),
        },
      })
    })

    expect(result.current.chain?.rows[0].call).toBeNull()
    expect(animationFrameCallbacks).toHaveLength(1)

    act(() => {
      animationFrameCallbacks.splice(0).forEach((callback) => callback(0))
    })

    expect(result.current.chain?.rows[0].call?.bid).toBe(1)
    expect(result.current.chain?.rows[1].put?.bid).toBe(2)
  })

  it('aborts an in-flight chain request on cleanup', async () => {
    const { unmount } = renderHook(() =>
      useOptionChain(analysis, '2026-06-19', false),
    )

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1)
    })

    const requestSignal = vi.mocked(fetch).mock.calls[0][1]?.signal
    expect(requestSignal?.aborted).toBe(false)

    unmount()

    expect(requestSignal?.aborted).toBe(true)
  })
})
