// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { connectWithBackoff } from '@/lib/connectWithBackoff'

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  close = vi.fn(() => {
    expect(vi.getTimerCount()).toBe(0)
    this.onclose?.()
  })
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }
}

describe('connectWithBackoff', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('doubles reconnect waits up to ten seconds and resets the wait on open', () => {
    const disconnect = connectWithBackoff('ws://localhost/stream')

    for (const delay of [1_000, 2_000, 4_000, 8_000, 10_000, 10_000]) {
      const count = FakeWebSocket.sockets.length
      FakeWebSocket.sockets.at(-1)?.onclose?.()
      vi.advanceTimersByTime(delay - 1)
      expect(FakeWebSocket.sockets).toHaveLength(count)
      vi.advanceTimersByTime(1)
      expect(FakeWebSocket.sockets).toHaveLength(count + 1)
    }

    FakeWebSocket.sockets.at(-1)?.onopen?.()
    FakeWebSocket.sockets.at(-1)?.onclose?.()
    vi.advanceTimersByTime(999)
    expect(FakeWebSocket.sockets).toHaveLength(7)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.sockets).toHaveLength(8)
    disconnect()
  })

  it('ignores callbacks and cancels the pending reconnect before closing on cleanup', () => {
    const onMessage = vi.fn()
    const onError = vi.fn()
    const onClose = vi.fn()
    const disconnect = connectWithBackoff('ws://localhost/stream', {
      onMessage, onError, onClose,
    })
    const [socket] = FakeWebSocket.sockets
    socket.onclose?.()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(1)

    disconnect()
    socket.onmessage?.(new MessageEvent('message', { data: 'late' }))
    socket.onerror?.()
    socket.onclose?.()
    vi.runAllTimers()

    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(onMessage).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(FakeWebSocket.sockets).toHaveLength(1)
  })

  it('reads the current URL at reconnect and forwards each live socket and message', () => {
    let account = 'DU1'
    const onConnect = vi.fn()
    const onMessage = vi.fn()
    const disconnect = connectWithBackoff(
      () => `ws://localhost/analysis?account=${account}`,
      { onConnect, onMessage },
    )
    const [first] = FakeWebSocket.sockets
    account = 'DU2'
    first.onclose?.()
    vi.advanceTimersByTime(1_000)
    const second = FakeWebSocket.sockets[1]
    const message = new MessageEvent('message', { data: 'snapshot' })
    second.onmessage?.(message)

    expect(first.url).toContain('account=DU1')
    expect(second.url).toContain('account=DU2')
    expect(onConnect.mock.calls).toEqual([[first], [second]])
    expect(onMessage).toHaveBeenCalledWith(message)
    disconnect()
  })
})
