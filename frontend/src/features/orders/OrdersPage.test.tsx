// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  amendOrder,
  cancelOrder,
  type OrderPreviewableRequest,
  type OrderRecord,
} from '@/api/orders'
import { OrdersPage } from '@/features/orders/OrdersPage'

vi.mock('@/api/orders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/orders')>()
  return {
    ...actual,
    amendOrder: vi.fn(),
    cancelOrder: vi.fn(),
  }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

describe('OrdersPage', () => {
  it('shows active orders separately from current-day history', () => {
    render(
      <OrdersPage
        orders={[
          orderRecord({ order_id: 700, status: 'working' }),
          orderRecord({ order_id: 701, status: 'filled' }),
          orderRecord({
            order_id: 702,
            status: 'cancelled',
            updated_at: '2020-01-01T00:00:00Z',
          }),
        ]}
      />,
    )

    expect(screen.getByText('#700')).toBeTruthy()
    expect(screen.getByText('#701')).toBeTruthy()
    expect(screen.queryByText('#702')).toBeNull()
  })

  it('cancels active orders with the submitted account', async () => {
    vi.mocked(cancelOrder).mockResolvedValue({
      order: orderRecord({ order_id: 700, status: 'cancelled' }),
      message: 'Cancelled order 700.',
    })

    render(<OrdersPage orders={[orderRecord({ order_id: 700, status: 'working' })]} />)
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    fireEvent.click(await screen.findByRole('button', { name: /cancel order/i }))

    await waitFor(() => {
      expect(cancelOrder).toHaveBeenCalledWith(700, { account: 'DU1234567' })
    })
  })

  it('amends permitted active option order fields', async () => {
    vi.mocked(amendOrder).mockResolvedValue({
      order: orderRecord({ order_id: 700, status: 'working' }),
      message: 'Updated order 700.',
    })

    render(
      <OrdersPage
        orders={[
          orderRecord({
            order_id: 700,
            status: 'working',
            request: {
              order_kind: 'option_strategy',
              account: 'DU1234567',
              limit_price: 1.25,
              take_profit_price: 2.5,
              stop_loss_price: 0.75,
              time_in_force: 'DAY',
              legs: [
                {
                  ticker: 'AAPL',
                  expiration: '2026-06-19',
                  right: 'CALL',
                  strike: 200,
                  action: 'BUY',
                  quantity: 1,
                },
              ],
            },
          }),
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    fireEvent.change(screen.getByLabelText('Limit price 700'), {
      target: { value: '1.35' },
    })
    fireEvent.change(screen.getByLabelText('Take profit 700'), {
      target: { value: '2.75' },
    })
    fireEvent.change(screen.getByLabelText('Stop loss 700'), {
      target: { value: '0.8' },
    })
    fireEvent.click(screen.getByLabelText('Time in force 700'))
    fireEvent.click(await screen.findByRole('option', { name: 'GTC' }))
    fireEvent.click(screen.getByRole('button', { name: /save order 700/i }))

    await waitFor(() => {
      expect(amendOrder).toHaveBeenCalledWith(700, {
        account: 'DU1234567',
        limit_price: 1.35,
        take_profit_price: 2.75,
        stop_loss_price: 0.8,
        time_in_force: 'GTC',
      })
    })
  })

  it('does not show edit controls for non-editable reconciled orders', () => {
    render(
      <OrdersPage
        orders={[orderRecord({ order_id: 700, status: 'working', editable: false })]}
      />,
    )

    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull()
    expect(screen.getByText('Reconciled from IB, not editable')).toBeTruthy()
  })
})

function orderRecord(
  overrides: Partial<OrderRecord> & { request?: OrderPreviewableRequest } = {},
): OrderRecord {
  const request = overrides.preview?.request ?? overrides.request ?? {
    order_kind: 'stock' as const,
    account: 'DU1234567',
    ticker: 'AAPL',
    action: 'BUY' as const,
    quantity: 10,
    order_type: 'LIMIT' as const,
    limit_price: 190.5,
    time_in_force: 'DAY' as const,
  }

  return {
    order_id: 700,
    perm_id: null,
    parent_order_id: null,
    account: 'DU1234567',
    status: 'working',
    editable: true,
    filled: 0,
    remaining: 10,
    avg_fill_price: null,
    rejection_message: null,
    submitted_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    preview: {
      preview_id: 'preview-1',
      account: 'DU1234567',
      order_kind: request.order_kind,
      summary:
        request.order_kind === 'stock'
          ? 'BUY 10 share(s) AAPL'
          : 'BUY 1 AAPL 2026-06-19 200 CALL @ 1.25',
      time_in_force: request.time_in_force ?? 'DAY',
      estimated_order_type: 'LIMIT',
      request,
    },
    ...withoutRequest(overrides),
  }
}

function withoutRequest<T extends { request?: OrderPreviewableRequest }>(
  value: T,
) {
  const rest = { ...value }
  delete rest.request
  return rest
}
