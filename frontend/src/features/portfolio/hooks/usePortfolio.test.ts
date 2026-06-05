// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []

  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  close() {
    this.onclose?.()
  }

  receive(snapshot: PortfolioResponse) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(snapshot) }))
  }
}

const snapshot: PortfolioResponse = {
  status: {
    connected: true,
    host: '127.0.0.1',
    port: 7497,
    client_id: 1,
  },
  accounts: [],
  positions: [],
  message: null,
}

describe('usePortfolio', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('retains the last snapshot and reconnects after the stream closes', () => {
    const { result, unmount } = renderHook(() => usePortfolio())

    expect(FakeWebSocket.sockets).toHaveLength(1)

    act(() => {
      FakeWebSocket.sockets[0].receive(snapshot)
    })
    act(() => {
      FakeWebSocket.sockets[0].onclose?.()
    })

    expect(result.current.portfolio).toEqual(snapshot)
    expect(result.current.error).toBe('Portfolio stream disconnected.')

    act(() => {
      vi.advanceTimersByTime(1_000)
    })

    expect(FakeWebSocket.sockets).toHaveLength(2)

    unmount()
    act(() => {
      vi.runAllTimers()
    })

    expect(FakeWebSocket.sockets).toHaveLength(2)
  })

  it('leaves loading state when the initial stream errors before a snapshot', () => {
    const { result } = renderHook(() => usePortfolio())

    expect(result.current.isLoading).toBe(true)

    act(() => {
      FakeWebSocket.sockets[0].onerror?.()
    })

    expect(result.current.portfolio).toBeNull()
    expect(result.current.error).toBe('Portfolio stream disconnected.')
    expect(result.current.isLoading).toBe(false)
  })

  it('leaves loading state and reconnects when the initial stream closes before a snapshot', () => {
    const { result } = renderHook(() => usePortfolio())

    expect(result.current.isLoading).toBe(true)

    act(() => {
      FakeWebSocket.sockets[0].onclose?.()
    })

    expect(result.current.portfolio).toBeNull()
    expect(result.current.error).toBe('Portfolio stream disconnected.')
    expect(result.current.isLoading).toBe(false)

    act(() => {
      vi.advanceTimersByTime(1_000)
    })

    expect(FakeWebSocket.sockets).toHaveLength(2)
  })
})
