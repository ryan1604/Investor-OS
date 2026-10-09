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
  it('uses backend section membership for open and history', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({
            order_id: 700,
            status: 'stale',
            is_open: false,
            reconciliation_status: 'stale',
          }),
          orderRecord({ order_id: 701, status: 'filled' }),
          orderRecord({
            order_id: 702,
            status: 'cancelled',
            is_current_day_history: true,
            updated_at: '2020-01-01T00:00:00Z',
          }),
        ]}
      />,
    )

    expect(screen.getByText('API order 701')).toBeTruthy()
    expect(screen.getByText('API order 702')).toBeTruthy()
    expect(screen.queryByText('API order 700')).toBeNull()
  })

  it('filters open and current-day history to the selected account', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({ order_id: 700, account: 'DU1234567', status: 'working' }),
          orderRecord({
            order_id: 701,
            account: 'DU7654321',
            status: 'working',
            request: { ...stockRequest(), account: 'DU7654321' },
          }),
          orderRecord({ order_id: 702, account: 'DU1234567', status: 'filled' }),
          orderRecord({
            order_id: 703,
            account: 'DU7654321',
            status: 'filled',
            request: { ...stockRequest(), account: 'DU7654321' },
          }),
        ]}
      />,
    )

    expect(screen.getByText('API order 700')).toBeTruthy()
    expect(screen.getByText('API order 702')).toBeTruthy()
    expect(screen.queryByText('API order 701')).toBeNull()
    expect(screen.queryByText('API order 703')).toBeNull()
  })

  it('does not expose a manual order refresh button', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[orderRecord({ order_id: 700, status: 'working' })]}
      />,
    )

    expect(screen.queryByRole('button', { name: /refresh/i })).toBeNull()
  })

  it('shows order load warnings', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[]}
        warning="Order load failed."
      />,
    )

    expect(screen.getByText('Order load failed.')).toBeTruthy()
  })

  it('cancels active orders with the submitted account', async () => {
    vi.mocked(cancelOrder).mockResolvedValue({
      order: orderRecord({ order_id: 700, status: 'cancelled' }),
      message: 'Cancelled order 700.',
    })

    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[orderRecord({ order_id: 700, status: 'working' })]}
      />,
    )
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
        {...ordersPageProps()}
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
          orderRecord({
            order_id: 701,
            parent_order_id: 700,
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
          orderRecord({
            order_id: 702,
            parent_order_id: 700,
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
        quantity: 1,
        limit_price: 1.35,
        take_profit_price: 2.75,
        stop_loss_price: 0.8,
        time_in_force: 'GTC',
      })
    })
  })

  it.each([
    [undefined, undefined],
    [undefined, null],
    [null, undefined],
    [null, null],
  ])('allows editing an order with no exit prices (TP: %s, SL: %s)', (takeProfitPrice, stopLossPrice) => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({
            order_id: 700,
            status: 'working',
            request: {
              order_kind: 'option_strategy',
              account: 'DU1234567',
              limit_price: 1.25,
              take_profit_price: takeProfitPrice,
              stop_loss_price: stopLossPrice,
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

    expect(screen.queryByText('Linked exit orders are incomplete.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    expect(screen.getByLabelText('Quantity 700')).toBeTruthy()
  })

  it('does not show edit controls for non-editable reconciled orders', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({
            order_id: 700,
            status: 'working',
            editable: false,
            read_only_reason: 'Order is visible but not bound for modification.',
          }),
        ]}
      />,
    )

    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull()
    expect(
      screen.getByText('Order is visible but not bound for modification.'),
    ).toBeTruthy()
  })

  it('shows pending rows in Open and keeps stale rows out', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({
            order_id: 700,
            status: 'working',
            reconciliation_status: 'pending',
          }),
          orderRecord({
            order_id: 701,
            status: 'working',
            reconciliation_status: 'stale',
          }),
        ]}
      />,
    )

    expect(screen.getByText('API order 700')).toBeTruthy()
    expect(screen.getByText('Pending IB confirmation')).toBeTruthy()
    expect(screen.queryByText('API order 701')).toBeNull()
  })

  it('renders linked bracket orders as one editable group', async () => {
    vi.mocked(amendOrder).mockResolvedValue({
      order: orderRecord({ order_id: 700, status: 'working' }),
      message: 'Updated order 700.',
    })
    const request: OrderPreviewableRequest = {
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
    }

    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({ order_id: 700, status: 'working', request }),
          orderRecord({
            order_id: 701,
            parent_order_id: 700,
            status: 'working',
            request,
          }),
          orderRecord({
            order_id: 702,
            parent_order_id: 700,
            status: 'working',
            request,
          }),
        ]}
      />,
    )

    expect(screen.getByText('API order 700')).toBeTruthy()
    expect(screen.queryByText('API order 701')).toBeNull()
    expect(screen.getByText('Linked order #701')).toBeTruthy()
    expect(screen.getByText('Linked order #702')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    fireEvent.change(screen.getByLabelText('Quantity 700'), {
      target: { value: '3' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save order 700/i }))

    await waitFor(() => {
      expect(amendOrder).toHaveBeenCalledWith(
        700,
        expect.objectContaining({ quantity: 3 }),
      )
    })
  })

  it('renders backend summary as primary and negative API ID as metadata', () => {
    render(
      <OrdersPage
        {...ordersPageProps()}
        orders={[
          orderRecord({
            order_id: -23,
            status: 'filled',
            is_current_day_history: true,
            display_details: ['Perm ID 45678', 'Execution 0002.def', 'API order -23'],
            preview: {
              preview_id: 'ib-execution--23',
              account: 'DU1234567',
              order_kind: 'stock',
              summary: 'SELL 5 AAPL STK @ 205.25',
              time_in_force: 'DAY',
              estimated_order_type: 'IB_EXECUTION',
              request: {
                order_kind: 'stock',
                account: 'DU1234567',
                ticker: 'AAPL',
                action: 'SELL',
                quantity: 5,
              },
            },
          }),
        ]}
      />,
    )

    expect(screen.getByText('SELL 5 AAPL STK @ 205.25')).toBeTruthy()
    expect(
      screen.getByText('Perm ID 45678 | Execution 0002.def | API order -23'),
    ).toBeTruthy()
    expect(screen.queryByText('#-23')).toBeNull()
  })
})

function ordersPageProps() {
  return {
    accounts: ['DU1234567'],
    selectedAccount: 'DU1234567',
    onSelectedAccountChange: vi.fn(),
  }
}

function stockRequest(): OrderPreviewableRequest {
  return {
    order_kind: 'stock',
    account: 'DU1234567',
    ticker: 'AAPL',
    action: 'BUY',
    quantity: 10,
    order_type: 'LIMIT',
    limit_price: 190.5,
    time_in_force: 'DAY',
  }
}

function orderRecord(
  overrides: Partial<OrderRecord> & { request?: OrderPreviewableRequest } = {},
): OrderRecord {
  const request = overrides.preview?.request ?? overrides.request ?? stockRequest()

  return {
    order_id: 700,
    perm_id: null,
    parent_order_id: null,
    account: 'DU1234567',
    status: 'working',
    reconciliation_status: 'confirmed',
    editable: true,
    read_only_reason: null,
    filled: 0,
    remaining: 10,
    avg_fill_price: null,
    rejection_message: null,
    display_details: [`API order ${overrides.order_id ?? 700}`],
    submitted_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_open:
      ['submitted', 'working', 'partially_filled'].includes(
        overrides.status ?? 'working',
      ) && (overrides.reconciliation_status ?? 'confirmed') !== 'stale',
    is_current_day_history: ['filled', 'cancelled', 'rejected'].includes(
      overrides.status ?? 'working',
    ),
    preview: {
      preview_id: 'preview-1',
      account: request.account,
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
