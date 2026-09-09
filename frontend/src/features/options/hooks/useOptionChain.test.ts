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
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not restart transports when a live chart update replaces analysis', async () => {
    const { result, rerender, unmount } = renderHook(
      ({ currentAnalysis }) =>
        useOptionChain(currentAnalysis, '2026-06-19', false),
      { initialProps: { currentAnalysis: analysis } },
    )

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))
    expect(result.current.isChainLoading).toBe(true)
    expect(fetch).not.toHaveBeenCalled()

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        rows: [],
        message: 'Streaming 0 strike(s).',
      })
    })

    expect(result.current.chain?.rows).toEqual([])
    expect(result.current.isChainLoading).toBe(false)

    rerender({
      currentAnalysis: {
        ...analysis,
        underlying_price: 103,
        candles: [{ ...analysis.candles[0], close: 103 }],
      },
    })

    expect(fetch).not.toHaveBeenCalled()
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

    const { result } = renderHook(() =>
      useOptionChain(analysis, '2026-06-19', false),
    )

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        ticker: chainWithRows.ticker,
        expiration: chainWithRows.expiration,
        rows: chainWithRows.rows,
        message: chainWithRows.message,
      })
    })

    expect(result.current.chain?.rows).toHaveLength(2)

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

  it('replaces fallback rows when a delta-window snapshot arrives', async () => {
    const { result } = renderHook(() =>
      useOptionChain(analysis, '2026-06-19', false),
    )

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        rows: [
          { strike: 90, call: quote({ delta: 0.02 }), put: null },
          { strike: 95, call: quote({ delta: 0.1 }), put: null },
          { strike: 100, call: null, put: quote({ delta: -0.1 }) },
        ],
        message: null,
      })
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        row: { strike: 90, call: quote({ bid: 3 }), put: null },
      })
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        rows: [
          { strike: 95, call: quote({ delta: 0.1 }), put: null },
          { strike: 100, call: null, put: quote({ delta: -0.1 }) },
        ],
        message: null,
      })
    })

    act(() => {
      animationFrameCallbacks.splice(0).forEach((callback) => callback(0))
    })

    expect(result.current.chain?.rows.map((row) => row.strike)).toEqual([
      95,
      100,
    ])
  })

  it('clears stream errors after a valid active snapshot', async () => {
    const { result } = renderHook(() =>
      useOptionChain(analysis, '2026-06-19', false),
    )

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    act(() => {
      FakeWebSocket.sockets[0].onerror?.()
    })
    expect(result.current.chainError).toBe('Option chain stream disconnected.')

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        rows: [{ strike: 100, call: null, put: null }],
        message: null,
      })
    })

    expect(result.current.chainError).toBeNull()

    act(() => {
      FakeWebSocket.sockets[0].onerror?.()
    })
    expect(result.current.chainError).toBe('Option chain stream disconnected.')

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        row: { strike: 100, call: quote({ bid: 1 }), put: null },
      })
    })

    expect(result.current.chainError).toBeNull()
  })

  it('closes the old stream when expiration changes', async () => {
    const { rerender, unmount } = renderHook(
      ({ expiration }) => useOptionChain(analysis, expiration, false),
      { initialProps: { expiration: '2026-06-19' } },
    )

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    rerender({ expiration: '2026-06-26' })

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(2))
    expect(FakeWebSocket.sockets[0].closed).toBe(true)
    expect(FakeWebSocket.sockets[1].closed).toBe(false)
    expect(fetch).not.toHaveBeenCalled()

    unmount()

    expect(FakeWebSocket.sockets[1].closed).toBe(true)
  })

  it('pauses while hidden and reconnects once with the retained chain', async () => {
    const { result, rerender } = renderHook(
      ({ isActive }) =>
        useOptionChain(analysis, '2026-06-19', false, isActive),
      { initialProps: { isActive: true } },
    )

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        ticker: 'AAPL',
        expiration: '2026-06-19',
        rows: [{ strike: 100, call: quote({ bid: 1 }), put: null }],
        message: null,
      })
    })
    expect(result.current.chain?.rows[0].call?.bid).toBe(1)

    rerender({ isActive: false })

    expect(FakeWebSocket.sockets[0].closed).toBe(true)
    expect(FakeWebSocket.sockets).toHaveLength(1)
    expect(result.current.chain?.rows[0].call?.bid).toBe(1)

    rerender({ isActive: true })

    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(2))
    expect(FakeWebSocket.sockets[1].closed).toBe(false)
    expect(result.current.chain?.rows[0].call?.bid).toBe(1)
  })
})
