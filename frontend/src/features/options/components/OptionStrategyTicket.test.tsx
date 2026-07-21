// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import {
  previewOrder,
  transmitOrder,
  type OptionStrategyOrderRequest,
  type OrderPreviewResponse,
} from '@/api/orders'
import { OptionStrategyTicket } from '@/features/options/components/OptionStrategyTicket'
import type { DraftOptionLeg } from '@/features/options/lib/strategyLegs'

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
  positions: [],
  message: null,
}

const legs: DraftOptionLeg[] = [
  {
    ticker: 'AAPL',
    expiration: '2026-06-19',
    right: 'CALL',
    strike: 200,
    signedQuantity: 1,
    quote: 2.5,
    bid: 2.4,
    ask: 2.5,
  },
  {
    ticker: 'AAPL',
    expiration: '2026-06-19',
    right: 'CALL',
    strike: 210,
    signedQuantity: -1,
    quote: 1,
    bid: 1,
    ask: 1.1,
  },
]

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('OptionStrategyTicket', () => {
  it('stays closed until the strategy action opens it', () => {
    renderTicket({ open: false })

    expect(screen.queryByText('Option strategy')).toBeNull()
  })

  it('keeps draft legs when the drawer is dismissed', () => {
    const onLegsChange = vi.fn()
    const onOpenChange = vi.fn()
    renderTicket({ onLegsChange, onOpenChange })

    fireEvent.click(screen.getByRole('button', { name: /close/i }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(onLegsChange).not.toHaveBeenCalled()
  })

  it('shows bid and ask prices for each leg', () => {
    renderTicket()

    expect(screen.getByRole('columnheader', { name: 'Bid' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: 'Ask' })).toBeTruthy()
    expect(screen.getByText('2.40')).toBeTruthy()
    expect(screen.getByText('2.50')).toBeTruthy()
    expect(screen.getByText('1.00')).toBeTruthy()
    expect(screen.getByText('1.10')).toBeTruthy()
  })

  it('clears draft legs when the cancel button is clicked', () => {
    const onLegsChange = vi.fn()
    const onOpenChange = vi.fn()
    renderTicket({ onLegsChange, onOpenChange })

    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(onLegsChange).toHaveBeenCalledWith([])
  })

  it('previews signed legs as buy and sell strategy legs', async () => {
    vi.mocked(previewOrder).mockResolvedValue(previewResponse())

    renderTicket()
    expect(screen.queryByRole('combobox', { name: /strategy account/i })).toBeNull()
    expect(screen.getByText('DU222')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    await waitFor(() => {
      expect(previewOrder).toHaveBeenCalledWith({
        order_kind: 'option_strategy',
        account: 'DU222',
        limit_price: 1.5,
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
          {
            ticker: 'AAPL',
            expiration: '2026-06-19',
            right: 'CALL',
            strike: 210,
            action: 'SELL',
            quantity: 1,
          },
        ],
      })
    })
  })

  it('shows a positive CSP credit while preserving the signed request price', async () => {
    vi.mocked(previewOrder).mockResolvedValue(
      previewResponse({
        request: {
          order_kind: 'option_strategy',
          account: 'DU222',
          limit_price: -1,
          time_in_force: 'DAY',
          legs: [
            {
              ticker: 'AAPL',
              expiration: '2026-06-19',
              right: 'CALL',
              strike: 210,
              action: 'SELL',
              quantity: 1,
            },
          ],
        },
      }),
    )

    render(
      <OptionStrategyTicket
        legs={[legs[1]]}
        open
        portfolio={portfolio}
        selectedAccount="DU222"
        creditEntry
        selectedAccountOnly
        onLegsChange={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    )

    expect(
      (screen.getByLabelText('Net limit credit') as HTMLInputElement).value,
    ).toBe('1.00')
    expect(screen.getByText('Net credit')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    await waitFor(() => {
      expect(previewOrder).toHaveBeenCalledWith(
        expect.objectContaining({ limit_price: -1 }),
      )
    })
  })

  it('opens without an account but blocks review until one is selected', () => {
    render(
      <OptionStrategyTicket
        legs={[legs[1]]}
        open
        portfolio={portfolio}
        selectedAccount={null}
        creditEntry
        selectedAccountOnly
        onLegsChange={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Option strategy')).toBeTruthy()
    expect(screen.getByText('No account selected')).toBeTruthy()
    expect(screen.getByText('Select an account.')).toBeTruthy()
    expect(screen.queryByRole('combobox', { name: /strategy account/i })).toBeNull()
    expect(
      (screen.getByRole('button', { name: /review/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('adds enabled bracket exit prices to option strategy previews', async () => {
    const bracketRequest: OptionStrategyOrderRequest = {
      order_kind: 'option_strategy',
      account: 'DU222',
      limit_price: 1.5,
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
        {
          ticker: 'AAPL',
          expiration: '2026-06-19',
          right: 'CALL',
          strike: 210,
          action: 'SELL',
          quantity: 1,
        },
      ],
    }
    vi.mocked(previewOrder).mockResolvedValue(
      previewResponse({
        estimated_order_type: 'LIMIT + BRACKET',
        request: bracketRequest,
      }),
    )

    renderTicket()
    fireEvent.click(screen.getByLabelText('Take profit'))
    fireEvent.change(screen.getByLabelText('Take profit price'), {
      target: { value: '2.50' },
    })
    fireEvent.click(screen.getByLabelText('Stop loss'))
    fireEvent.change(screen.getByLabelText('Stop loss price'), {
      target: { value: '0.75' },
    })
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    await waitFor(() => {
      expect(previewOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          take_profit_price: 2.5,
          stop_loss_price: 0.75,
        }),
      )
    })
    expect(await screen.findByText('2.50')).toBeTruthy()
    expect(await screen.findByText('0.75')).toBeTruthy()
  })

  it('lets users edit signed quantities and removes zero-net legs', () => {
    const onLegsChange = vi.fn()
    renderTicket({ onLegsChange })

    fireEvent.change(screen.getByLabelText('Quantity 200 CALL'), {
      target: { value: '2' },
    })
    expect(onLegsChange).toHaveBeenCalledWith([
      { ...legs[0], signedQuantity: 2 },
      legs[1],
    ])

    fireEvent.change(screen.getByLabelText('Quantity 200 CALL'), {
      target: { value: '0' },
    })
    expect(onLegsChange).toHaveBeenLastCalledWith([legs[1]])
  })

  it('transmits the previewed option strategy', async () => {
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
})

function renderTicket({
  onLegsChange = vi.fn(),
  onOpenChange = vi.fn(),
  open = true,
}: {
  onLegsChange?: (legs: DraftOptionLeg[]) => void
  onOpenChange?: (open: boolean) => void
  open?: boolean
} = {}) {
  return render(
    <OptionStrategyTicket
      legs={legs}
      open={open}
      portfolio={portfolio}
      selectedAccount="DU222"
      onLegsChange={onLegsChange}
      onOpenChange={onOpenChange}
    />,
  )
}

function previewResponse(
  overrides: Partial<OrderPreviewResponse> = {},
): OrderPreviewResponse {
  return {
    preview_id: 'preview-1',
    account: 'DU222',
    order_kind: 'option_strategy',
    summary:
      'BUY 1 AAPL 2026-06-19 200 CALL, SELL 1 AAPL 2026-06-19 210 CALL @ 1.5',
    time_in_force: 'DAY',
    estimated_order_type: 'LIMIT',
    request: {
      order_kind: 'option_strategy',
      account: 'DU222',
      limit_price: 1.5,
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
        {
          ticker: 'AAPL',
          expiration: '2026-06-19',
          right: 'CALL',
          strike: 210,
          action: 'SELL',
          quantity: 1,
        },
      ],
    },
    ...overrides,
  }
}
