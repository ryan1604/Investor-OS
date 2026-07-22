// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import { previewOrder, transmitOrder, type OrderPreviewResponse } from '@/api/orders'
import { StockTradeTicket } from '@/features/options/components/StockTradeTicket'

vi.mock('@/api/orders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/orders')>()
  return {
    ...actual,
    previewOrder: vi.fn(),
    transmitOrder: vi.fn(),
  }
})

const portfolio: PortfolioResponse = {
  status: {
    connected: true,
    host: '127.0.0.1',
    port: 7497,
    client_id: 1,
  },
  accounts: [
    {
      account: 'DU111',
      currency: 'USD',
      net_liquidation: null,
      daily_pnl: null,
      daily_pnl_percent: null,
      unrealized_pnl: null,
      market_value: null,
      maintenance_margin: null,
      excess_liquidity: null,
      buying_power: null,
      cash_total_sgd: null,
      cash_total_usd: null,
      cash_total: null,
    },
    {
      account: 'DU222',
      currency: 'USD',
      net_liquidation: null,
      daily_pnl: null,
      daily_pnl_percent: null,
      unrealized_pnl: null,
      market_value: null,
      maintenance_margin: null,
      excess_liquidity: null,
      buying_power: null,
      cash_total_sgd: null,
      cash_total_usd: null,
      cash_total: null,
    },
  ],
  positions: [
    {
      account: 'DU222',
      symbol: 'AAPL',
      sec_type: 'STK',
      local_symbol: null,
      expiry: null,
      strike: null,
      right: null,
      multiplier: null,
      exchange: 'NASDAQ',
      currency: 'USD',
      quantity: 5,
      average_cost: 175,
      last_price: 190,
      change_percent: null,
      pnl: null,
      pnl_percent: null,
      unrealized_pnl: null,
      unrealized_pnl_percent: null,
      market_value: null,
      cost_basis: null,
      average_price: null,
      net_liquidity: null,
      net_liquidity_percent: null,
    },
  ],
  message: null,
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('StockTradeTicket', () => {
  it('defaults to the selected account and previews a market share buy', async () => {
    vi.mocked(previewOrder).mockResolvedValue(previewResponse())

    renderTicket()
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))

    expect(screen.queryByRole('button', { name: 'USD' })).toBeNull()
    expect(screen.queryByRole('combobox', { name: /account/i })).toBeNull()
    expect(screen.getByText('DU222')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    await waitFor(() => {
      expect(previewOrder).toHaveBeenCalledWith({
        order_kind: 'stock',
        account: 'DU222',
        ticker: 'AAPL',
        action: 'BUY',
        quantity: 1,
        order_type: 'MARKET',
        limit_price: null,
        time_in_force: 'DAY',
      })
    })
    expect(await screen.findByText('BUY 1 share(s) AAPL')).toBeTruthy()
  })

  it('blocks fractional share quantities', () => {
    renderTicket()
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))
    fireEvent.change(screen.getByLabelText('Shares'), {
      target: { value: '1.5' },
    })

    expect(screen.getByText('Enter a whole share quantity.')).toBeTruthy()
    expect(screen.getByRole('button', { name: /review/i })).toHaveProperty(
      'disabled',
      true,
    )
  })

  it('blocks review when no selected account is available', () => {
    render(
      <StockTradeTicket
        ticker="AAPL"
        latestPrice={190.12}
        portfolio={portfolio}
        selectedAccount={null}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))

    expect(screen.getByText('No account selected')).toBeTruthy()
    expect(screen.getByText('Select an account.')).toBeTruthy()
    expect(screen.queryByRole('combobox', { name: /account/i })).toBeNull()
    expect(screen.getByRole('button', { name: /review/i })).toHaveProperty(
      'disabled',
      true,
    )
  })

  it('blocks stock sells above the selected account position', () => {
    renderTicket()
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Sell' }))
    fireEvent.change(screen.getByLabelText('Shares'), { target: { value: '6' } })

    expect(
      screen.getByText('Sell quantity exceeds selected-account shares.'),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: /review/i })).toHaveProperty(
      'disabled',
      true,
    )
  })

  it('transmits the previewed order after confirmation', async () => {
    const preview = previewResponse()
    vi.mocked(previewOrder).mockResolvedValue(preview)
    vi.mocked(transmitOrder).mockResolvedValue({
      order: {
        order_id: 700,
        perm_id: null,
        parent_order_id: null,
        account: 'DU222',
        status: 'submitted',
        reconciliation_status: 'confirmed',
        editable: true,
        filled: 0,
        remaining: null,
        avg_fill_price: null,
        rejection_message: null,
        is_open: true,
        is_current_day_history: false,
        submitted_at: '2026-06-03T00:00:00Z',
        updated_at: '2026-06-03T00:00:00Z',
        preview,
      },
      message: 'Submitted order 700 to Interactive Brokers.',
    })

    renderTicket()
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))
    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    fireEvent.click(await screen.findByRole('button', { name: /transmit/i }))

    await waitFor(() => {
      expect(transmitOrder).toHaveBeenCalledWith(preview.request)
    })
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /close/i }).length).toBeGreaterThan(
        0,
      )
    })
  })

  it('resets review state when the dialog is closed and reopened', async () => {
    vi.mocked(previewOrder).mockResolvedValue(previewResponse())

    renderTicket()
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    expect(await screen.findByText('BUY 1 share(s) AAPL')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /^close$/i }))
    fireEvent.click(screen.getByRole('button', { name: /trade/i }))

    expect(screen.queryByText('BUY 1 share(s) AAPL')).toBeNull()
    expect(screen.getByRole('button', { name: /review/i })).toBeTruthy()
  })
})

function renderTicket() {
  return render(
    <StockTradeTicket
      ticker="AAPL"
      latestPrice={190.12}
      portfolio={portfolio}
      selectedAccount="DU222"
    />,
  )
}

function previewResponse(
  overrides: Partial<OrderPreviewResponse> = {},
): OrderPreviewResponse {
  return {
    preview_id: 'preview-1',
    account: 'DU222',
    order_kind: 'stock' as const,
    summary: 'BUY 1 share(s) AAPL',
    time_in_force: 'DAY' as const,
    estimated_order_type: 'MARKET',
    request: {
      order_kind: 'stock' as const,
      account: 'DU222',
      ticker: 'AAPL',
      action: 'BUY' as const,
      quantity: 1,
      order_type: 'MARKET' as const,
      limit_price: null,
      time_in_force: 'DAY' as const,
    },
    ...overrides,
  }
}
