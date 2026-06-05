// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { createElement, StrictMode, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  OptionsAnalysisResponse,
  OptionsChartLiveMessage,
} from '@/api/options'
import { useOptionsChartStream } from '@/features/options/hooks/useOptionsChartStream'

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []

  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  close() {
    this.closed = true
    this.onclose?.()
  }

  receive(update: OptionsChartLiveMessage) {
    this.onmessage?.(
      new MessageEvent('message', { data: JSON.stringify(update) }),
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
  bollinger_bands: [
    {
      date: '2026-05-30',
      upper: 102,
      middle: 100,
      lower: 98,
    },
  ],
  rsi: [{ date: '2026-05-30', value: 50 }],
  message: null,
}

const update: OptionsChartLiveMessage = {
  type: 'update',
  ticker: 'AAPL',
  candle: {
    date: '2026-05-30',
    open: 99,
    high: 104,
    low: 98,
    close: 103,
    volume: 2_000,
  },
  bollinger_band: {
    date: '2026-05-30',
    upper: 105,
    middle: 101,
    lower: 97,
  },
  rsi: { date: '2026-05-30', value: 61 },
}

describe('useOptionsChartStream', () => {
  beforeEach(() => {
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  it('replaces the active candle, ignores other tickers, and closes stale sockets', () => {
    const { result, rerender, unmount } = renderHook(
      ({ currentAnalysis }) => useOptionsChartStream(currentAnalysis),
      { initialProps: { currentAnalysis: analysis } },
    )

    expect(FakeWebSocket.sockets).toHaveLength(1)

    act(() => {
      FakeWebSocket.sockets[0].receive({ ...update, ticker: 'MSFT' })
    })
    expect(result.current.analysis?.underlying_price).toBe(100)

    act(() => {
      FakeWebSocket.sockets[0].receive({
        ...update,
        candle: { ...update.candle, date: '2026-05-29' },
      })
    })
    expect(result.current.analysis?.underlying_price).toBe(100)
    expect(result.current.latestUpdate).toBeNull()

    act(() => {
      FakeWebSocket.sockets[0].receive(update)
    })
    expect(result.current.analysis?.underlying_price).toBe(103)
    expect(result.current.analysis?.candles).toHaveLength(1)
    expect(result.current.analysis?.bollinger_bands[0].middle).toBe(100)
    expect(result.current.analysis?.rsi[0].value).toBe(50)
    expect(result.current.latestUpdate).toEqual(update)

    act(() => {
      FakeWebSocket.sockets[0].onclose?.()
    })
    expect(result.current.analysis?.underlying_price).toBe(103)
    expect(result.current.error).toBe('Options chart stream disconnected.')

    rerender({
      currentAnalysis: { ...analysis, ticker: 'MSFT' },
    })
    expect(FakeWebSocket.sockets[0].closed).toBe(true)
    expect(FakeWebSocket.sockets).toHaveLength(2)
    expect(result.current.error).toBeNull()

    unmount()
    expect(FakeWebSocket.sockets[1].closed).toBe(true)
  })

  it('does not show a disconnected error when cleanup closes an active ticker socket', () => {
    const { result, rerender, unmount } = renderHook(
      ({ currentAnalysis }) => useOptionsChartStream(currentAnalysis),
      { initialProps: { currentAnalysis: analysis } },
    )

    rerender({
      currentAnalysis: {
        ...analysis,
        underlying_price: 101,
      },
    })

    expect(FakeWebSocket.sockets[0].closed).toBe(true)
    expect(FakeWebSocket.sockets).toHaveLength(2)
    expect(result.current.error).toBeNull()

    unmount()

    expect(FakeWebSocket.sockets[1].closed).toBe(true)
    expect(result.current.error).toBeNull()
  })

  it('does not show a disconnected error during Strict Mode effect replay', () => {
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(StrictMode, null, children)

    const { result } = renderHook(() => useOptionsChartStream(analysis), {
      wrapper,
    })

    expect(result.current.error).toBeNull()
  })

  it('shows unexpected stream errors for the active ticker', () => {
    const { result } = renderHook(() => useOptionsChartStream(analysis))

    act(() => {
      FakeWebSocket.sockets[0].onerror?.()
    })

    expect(result.current.error).toBe('Options chart stream disconnected.')
  })

  it('shows a same-ticker refetch immediately after a live update', () => {
    const { result, rerender } = renderHook(
      ({ currentAnalysis }) => useOptionsChartStream(currentAnalysis),
      { initialProps: { currentAnalysis: analysis } },
    )

    act(() => {
      FakeWebSocket.sockets[0].receive(update)
    })
    expect(result.current.analysis?.underlying_price).toBe(103)
    expect(result.current.latestUpdate).toEqual(update)

    const refetchedAnalysis: OptionsAnalysisResponse = {
      ...analysis,
      underlying_price: 110,
      candles: [
        {
          ...analysis.candles[0],
          close: 110,
          volume: 3_000,
        },
      ],
      bollinger_bands: [
        {
          ...analysis.bollinger_bands[0],
          middle: 110,
        },
      ],
      rsi: [{ ...analysis.rsi[0], value: 55 }],
    }

    rerender({ currentAnalysis: refetchedAnalysis })

    expect(result.current.analysis).toEqual(refetchedAnalysis)
    expect(result.current.latestUpdate).toBeNull()

    const refetchUpdate: OptionsChartLiveMessage = {
      ...update,
      candle: {
        ...update.candle,
        close: 112,
        volume: 4_000,
      },
      bollinger_band: {
        ...update.bollinger_band,
        middle: 111,
      },
      rsi: { ...update.rsi, value: 58 },
    }

    act(() => {
      FakeWebSocket.sockets[1].receive(refetchUpdate)
    })

    expect(result.current.analysis?.underlying_price).toBe(112)
    expect(result.current.analysis?.candles[0].volume).toBe(3_000)
    expect(result.current.analysis?.bollinger_bands[0].middle).toBe(110)
    expect(result.current.analysis?.rsi[0].value).toBe(55)
    expect(result.current.latestUpdate).toEqual(refetchUpdate)
  })
})
