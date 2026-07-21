// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OrderRecord, OrderStatusUpdate } from '@/api/orders'
import { fetchOrders } from '@/api/orders'
import { useOrders } from '@/features/orders/hooks/useOrders'

vi.mock('@/api/orders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/orders')>()
  return {
    ...actual,
    fetchOrders: vi.fn(),
  }
})

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []

  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  close() {
    this.onclose?.()
  }

  receive(update: OrderStatusUpdate) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(update) }))
  }
}

function deferredOrders() {
  let resolve!: (orders: OrderRecord[]) => void
  const promise = new Promise<OrderRecord[]>((nextResolve) => {
    resolve = nextResolve
  })

  return { promise, resolve }
}

const basePreview: OrderRecord['preview'] = {
  preview_id: 'preview-1',
  account: 'DU123',
  order_kind: 'stock',
  summary: 'Buy 1 AAPL',
  time_in_force: 'DAY',
  estimated_order_type: 'LIMIT',
  request: {
    order_kind: 'stock',
    account: 'DU123',
    ticker: 'AAPL',
    action: 'BUY',
    quantity: 1,
    order_type: 'LIMIT',
    limit_price: 100,
    time_in_force: 'DAY',
  },
}

function orderRecord(overrides: Partial<OrderRecord> = {}): OrderRecord {
  return {
    order_id: 700,
    perm_id: null,
    parent_order_id: null,
    account: 'DU123',
    status: 'submitted',
    reconciliation_status: 'confirmed',
    editable: true,
    filled: 0,
    remaining: 1,
    avg_fill_price: null,
    rejection_message: null,
    is_open: ['submitted', 'working', 'partially_filled'].includes(
      overrides.status ?? 'submitted',
    ),
    is_current_day_history: ['filled', 'cancelled', 'rejected'].includes(
      overrides.status ?? 'submitted',
    ),
    submitted_at: '2026-06-04T10:00:00Z',
    updated_at: '2026-06-04T10:00:00Z',
    preview: basePreview,
    ...overrides,
  }
}

describe('useOrders', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.mocked(fetchOrders).mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('applies the bootstrap REST snapshot when it resolves before stream updates', async () => {
    const bootstrap = deferredOrders()
    vi.mocked(fetchOrders).mockReturnValue(bootstrap.promise)
    const bootstrapOrder = orderRecord()

    const { result } = renderHook(() => useOrders())

    await act(async () => {
      bootstrap.resolve([bootstrapOrder])
      await bootstrap.promise
    })

    expect(result.current.orders).toEqual([bootstrapOrder])
    expect(result.current.warning).toBeNull()
  })

  it('does not request reconciliation when the order stream opens', () => {
    vi.mocked(fetchOrders).mockResolvedValue([])

    renderHook(() => useOrders())

    act(() => {
      FakeWebSocket.sockets[0].onopen?.()
    })

    expect(fetchOrders).toHaveBeenCalledTimes(1)
  })

  it('does not let a delayed bootstrap REST snapshot overwrite a stream snapshot', async () => {
    const bootstrap = deferredOrders()
    vi.mocked(fetchOrders).mockReturnValue(bootstrap.promise)
    const streamedOrder = orderRecord({
      order_id: 701,
      status: 'working',
      updated_at: '2026-06-04T10:01:00Z',
    })

    const { result } = renderHook(() => useOrders())

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        orders: [streamedOrder],
        order: null,
      })
    })

    expect(result.current.orders).toEqual([streamedOrder])

    await act(async () => {
      bootstrap.resolve([orderRecord({ order_id: 700, status: 'submitted' })])
      await bootstrap.promise
    })

    expect(result.current.orders).toEqual([streamedOrder])
  })

  it('does not let a delayed bootstrap REST snapshot overwrite a stream update', async () => {
    const bootstrap = deferredOrders()
    vi.mocked(fetchOrders).mockReturnValue(bootstrap.promise)
    const streamedOrder = orderRecord({
      status: 'filled',
      filled: 1,
      remaining: 0,
      updated_at: '2026-06-04T10:02:00Z',
    })

    const { result } = renderHook(() => useOrders())

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        orders: null,
        order: streamedOrder,
      })
    })

    expect(result.current.orders).toEqual([streamedOrder])

    await act(async () => {
      bootstrap.resolve([orderRecord({ status: 'working' })])
      await bootstrap.promise
    })

    expect(result.current.orders).toEqual([streamedOrder])
  })

  it('upserts single-order stream updates after a stream snapshot', () => {
    vi.mocked(fetchOrders).mockReturnValue(new Promise(() => undefined))
    const submittedOrder = orderRecord({ status: 'submitted' })
    const workingOrder = orderRecord({
      status: 'working',
      updated_at: '2026-06-04T10:03:00Z',
    })

    const { result } = renderHook(() => useOrders())

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        orders: [submittedOrder],
        order: null,
      })
    })
    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        orders: null,
        order: workingOrder,
      })
    })

    expect(result.current.orders).toEqual([workingOrder])
  })

  it('rekeys stream updates by perm_id instead of appending duplicate rows', () => {
    vi.mocked(fetchOrders).mockReturnValue(new Promise(() => undefined))
    const staleOrder = orderRecord({
      order_id: 0,
      perm_id: 60285899,
      account: 'U6985190',
    })
    const boundOrder = orderRecord({
      order_id: -23,
      perm_id: 60285899,
      account: 'U6985190',
      status: 'working',
      updated_at: '2026-06-04T10:03:00Z',
    })

    const { result } = renderHook(() => useOrders())

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        orders: [staleOrder],
        order: null,
      })
    })
    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        orders: null,
        order: boundOrder,
      })
    })

    expect(result.current.orders).toEqual([boundOrder])
  })

  it('applies stream updates that move orders from open to current-day history', () => {
    vi.mocked(fetchOrders).mockReturnValue(new Promise(() => undefined))
    const openOrder = orderRecord({
      status: 'working',
      is_open: true,
      is_current_day_history: false,
    })
    const filledOrder = orderRecord({
      status: 'filled',
      filled: 1,
      remaining: 0,
      is_open: false,
      is_current_day_history: true,
      updated_at: '2026-06-04T10:04:00Z',
    })

    const { result } = renderHook(() => useOrders())

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        orders: [openOrder],
        order: null,
      })
    })
    expect(result.current.orders.filter((order) => order.is_open)).toEqual([openOrder])

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'update',
        orders: null,
        order: filledOrder,
      })
    })

    expect(result.current.orders.filter((order) => order.is_open)).toEqual([])
    expect(
      result.current.orders.filter((order) => order.is_current_day_history),
    ).toEqual([filledOrder])
  })

  it('surfaces bootstrap load failures until a stream update recovers', async () => {
    vi.mocked(fetchOrders).mockRejectedValue(new Error('Order load failed.'))
    const streamedOrder = orderRecord({ status: 'working' })

    const { result } = renderHook(() => useOrders())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.warning).toBe('Order load failed.')

    act(() => {
      FakeWebSocket.sockets[0].receive({
        type: 'snapshot',
        orders: [streamedOrder],
        order: null,
      })
    })

    expect(result.current.warning).toBeNull()
    expect(result.current.orders).toEqual([streamedOrder])
  })

  it('does not poll orders after the bootstrap snapshot', () => {
    vi.mocked(fetchOrders).mockResolvedValue([])

    renderHook(() => useOrders())
    act(() => {
      vi.advanceTimersByTime(60_000)
    })

    expect(fetchOrders).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect after cleanup', () => {
    vi.mocked(fetchOrders).mockResolvedValue([])
    const { unmount } = renderHook(() => useOrders())

    expect(FakeWebSocket.sockets).toHaveLength(1)

    act(() => {
      FakeWebSocket.sockets[0].onclose?.()
    })
    unmount()
    act(() => {
      vi.runAllTimers()
    })

    expect(FakeWebSocket.sockets).toHaveLength(1)
  })
})
