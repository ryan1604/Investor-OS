// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioAnalysisResponse } from '@/api/portfolioAnalysis'
import { usePortfolioAnalysis } from '@/features/portfolio-analysis/hooks/usePortfolioAnalysis'
import { analysisResponse } from '@/features/portfolio-analysis/testFixtures'

class FakeWebSocket {
  static OPEN = 1
  static sockets: FakeWebSocket[] = []

  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  readyState = 0
  sent: unknown[] = []
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  send(data: string) {
    this.sent.push(JSON.parse(data))
  }

  close() {
    this.closed = true
    this.onclose?.()
  }

  receive(analysis: PortfolioAnalysisResponse) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(analysis) }))
  }
}

describe('usePortfolioAnalysis', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('streams analysis for the account and closes the socket on unmount', () => {
    const { result, unmount } = renderHook(() => usePortfolioAnalysis('DU1'))
    const [socket] = FakeWebSocket.sockets

    expect(socket.url).toBe('ws://127.0.0.1:8000/portfolio/analysis/ws?account=DU1')
    expect(result.current.isLoading).toBe(true)

    act(() => {
      socket.open()
      socket.receive(analysisResponse())
    })
    expect(result.current.analysis?.summary.net_liquidation).toBe(100_000)
    expect(result.current.isLoading).toBe(false)

    unmount()
    vi.advanceTimersByTime(10_000)
    expect(socket.closed).toBe(true)
    expect(FakeWebSocket.sockets).toHaveLength(1)
  })

  it('switches accounts on the open socket and drops stale updates', () => {
    const { result, rerender } = renderHook(
      ({ account }) => usePortfolioAnalysis(account),
      { initialProps: { account: 'DU1' } },
    )
    const [socket] = FakeWebSocket.sockets
    act(() => {
      socket.open()
      socket.receive(analysisResponse())
    })

    rerender({ account: 'DU2' })
    expect(socket.sent).toEqual([{ account: 'DU2' }])

    act(() => {
      socket.receive(analysisResponse({ account: 'DU1' }))
    })
    expect(result.current.analysis?.account).toBe('DU1')
    act(() => {
      socket.receive(analysisResponse({ account: 'DU2', message: 'second' }))
    })
    expect(result.current.analysis?.message).toBe('second')
    act(() => {
      socket.receive(analysisResponse({ account: 'DU1', message: 'stale' }))
    })
    expect(result.current.analysis?.message).toBe('second')

    act(() => {
      result.current.refresh()
    })
    expect(socket.sent).toEqual([{ account: 'DU2' }, { account: 'DU2' }])
    expect(FakeWebSocket.sockets).toHaveLength(1)
  })

  it('keeps the last analysis and reconnects with the current account', () => {
    const { result, rerender } = renderHook(
      ({ account }) => usePortfolioAnalysis(account),
      { initialProps: { account: 'DU1' } },
    )
    act(() => {
      FakeWebSocket.sockets[0].receive(analysisResponse())
    })
    rerender({ account: 'DU2' })
    act(() => {
      FakeWebSocket.sockets[0].onclose?.()
    })

    expect(result.current.error).toBe('Portfolio Analysis stream disconnected.')
    expect(result.current.analysis?.account).toBe('DU1')

    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(FakeWebSocket.sockets).toHaveLength(2)
    expect(FakeWebSocket.sockets[1].url).toContain('?account=DU2')
  })
})
