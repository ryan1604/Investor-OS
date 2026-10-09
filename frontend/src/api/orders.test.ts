import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ORDERS_WS_URL,
  amendOrder,
  cancelOrder,
  fetchOrders,
  previewOrder,
  transmitOrder,
  type StockOrderRequest,
} from '@/api/orders'

const stockOrder: StockOrderRequest = {
  order_kind: 'stock',
  account: 'DU1234567',
  ticker: 'AAPL',
  action: 'BUY',
  quantity: 10,
  order_type: 'LIMIT',
  limit_price: 190.5,
  time_in_force: 'DAY',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('orders api', () => {
  it('posts preview and transmit requests to the shared order endpoints', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ preview_id: 'preview-1' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ order: { order_id: 700 } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await previewOrder(stockOrder)
    await transmitOrder(stockOrder)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/orders/preview',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(stockOrder),
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/orders/transmit',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(stockOrder),
      },
    )
  })

  it('posts cancellation requests by order id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ order: { order_id: 700 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await cancelOrder(700, { account: 'DU1234567' })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/orders/700/cancel',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: 'DU1234567' }),
      },
    )
  })

  it('fetches and amends orders', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ order_id: 700 }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ order: { order_id: 700 } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchOrders()
    await amendOrder(700, {
      account: 'DU1234567',
      quantity: 12,
      limit_price: 191.25,
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/orders',
      undefined,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/orders/700',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account: 'DU1234567',
          quantity: 12,
          limit_price: 191.25,
        }),
      },
    )
  })

  it('surfaces backend order errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'IB rejected this order.' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(transmitOrder(stockOrder)).rejects.toThrow(
      'IB rejected this order.',
    )
  })

  it('exports the order status websocket url', () => {
    expect(ORDERS_WS_URL).toBe('ws://127.0.0.1:8000/orders/ws')
  })
})
