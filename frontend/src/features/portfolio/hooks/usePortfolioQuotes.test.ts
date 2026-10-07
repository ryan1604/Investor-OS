// @vitest-environment jsdom

import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePortfolioQuotes } from '@/features/portfolio/hooks/usePortfolioQuotes'

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []

  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  url: string
  closed = false

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  close() {
    this.closed = true
    this.onclose?.()
  }
}

describe('usePortfolioQuotes', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('holds the quote socket while mounted and reconnects after drops', () => {
    const { unmount } = renderHook(() => usePortfolioQuotes())

    expect(FakeWebSocket.sockets).toHaveLength(1)
    expect(FakeWebSocket.sockets[0].url).toContain('/portfolio/quotes/ws')

    FakeWebSocket.sockets[0].onclose?.()
    vi.advanceTimersByTime(1_000)
    expect(FakeWebSocket.sockets).toHaveLength(2)

    unmount()
    vi.advanceTimersByTime(10_000)
    expect(FakeWebSocket.sockets).toHaveLength(2)
    expect(FakeWebSocket.sockets[1].closed).toBe(true)
  })
})
