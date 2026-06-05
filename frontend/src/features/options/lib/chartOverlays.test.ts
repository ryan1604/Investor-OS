import { describe, expect, it } from 'vitest'

import type { OrderRecord, OptionStrategyOrderRequest } from '@/api/orders'
import type { PortfolioPosition, PortfolioResponse } from '@/api/portfolio'
import { chartOverlays } from '@/features/options/lib/chartOverlays'
import type { DraftOptionLeg } from '@/features/options/lib/strategyLegs'

describe('chartOverlays', () => {
  it('shows selected-account stock cost basis without aggregating accounts', () => {
    const overlays = chartOverlays({
      draftLegs: [],
      orders: [],
      portfolio: portfolio([
        stockPosition({ account: 'DU1', average_price: 101 }),
        stockPosition({ account: 'DU2', average_price: 120 }),
      ]),
      selectedAccount: 'DU1',
      ticker: 'AAPL',
    })

    expect(overlays).toEqual([
      {
        type: 'stock-cost-basis',
        key: 'stock-cost-basis:DU1:AAPL',
        price: 101,
        label: 'Cost basis',
      },
    ])
  })

  it('hides stock cost basis when no account is explicitly selected', () => {
    const overlays = chartOverlays({
      draftLegs: [],
      orders: [],
      portfolio: portfolio([stockPosition({ average_price: 101 })]),
      selectedAccount: null,
      ticker: 'AAPL',
    })

    expect(overlays).toEqual([])
  })

  it('combines matching draft working and held option strikes', () => {
    const overlays = chartOverlays({
      draftLegs: [
        draftLeg({ signedQuantity: 1 }),
        draftLeg({ signedQuantity: -1, strike: 210 }),
      ],
      orders: [
        orderRecord({
          order_id: 700,
          status: 'working',
          parent_order_id: null,
          request: optionStrategyRequest({
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
          }),
        }),
        orderRecord({
          order_id: 701,
          status: 'working',
          parent_order_id: 700,
          request: optionStrategyRequest(),
        }),
      ],
      portfolio: portfolio([
        optionPosition({
          expiry: '20260619',
          right: 'C',
          strike: 200,
          quantity: 1,
        }),
      ]),
      selectedAccount: 'DU1',
      ticker: 'AAPL',
    })

    expect(overlays).toContainEqual({
      type: 'option-strike',
      key: 'option-strike:AAPL:20260619:CALL:200',
      ticker: 'AAPL',
      expiration: '20260619',
      right: 'CALL',
      strike: 200,
      signedQuantity: 3,
      sources: ['draft', 'working', 'held'],
      label: '+3 call',
    })
    expect(overlays).toContainEqual(
      expect.objectContaining({
        key: 'option-strike:AAPL:20260619:CALL:210',
        signedQuantity: -1,
        label: '-1 call',
        sources: ['draft'],
      }),
    )
  })

  it('keeps different expirations and rights separate and hides zero-net lines', () => {
    const overlays = chartOverlays({
      draftLegs: [
        draftLeg({ signedQuantity: 1, right: 'PUT' }),
        draftLeg({ signedQuantity: -1, right: 'PUT' }),
        draftLeg({ expiration: '2026-07-17', signedQuantity: -1, right: 'PUT' }),
      ],
      orders: [],
      portfolio: null,
      selectedAccount: 'DU1',
      ticker: 'AAPL',
    })

    expect(overlays).toEqual([
      expect.objectContaining({
        key: 'option-strike:AAPL:20260717:PUT:200',
        right: 'PUT',
        signedQuantity: -1,
        label: '-1 put',
      }),
    ])
  })

  it('drops working orders once they are no longer active', () => {
    const overlays = chartOverlays({
      draftLegs: [],
      orders: [
        orderRecord({
          order_id: 700,
          status: 'filled',
          parent_order_id: null,
          request: optionStrategyRequest(),
        }),
      ],
      portfolio: null,
      selectedAccount: 'DU1',
      ticker: 'AAPL',
    })

    expect(overlays).toEqual([])
  })
})

function portfolio(positions: PortfolioPosition[]): PortfolioResponse {
  return {
    status: {
      connected: true,
      host: '127.0.0.1',
      port: 7497,
      client_id: 1,
    },
    accounts: [],
    positions,
    message: null,
  }
}

function stockPosition(
  overrides: Partial<PortfolioPosition> = {},
): PortfolioPosition {
  return position({
    sec_type: 'STK',
    quantity: 10,
    average_price: 101,
    ...overrides,
  })
}

function optionPosition(
  overrides: Partial<PortfolioPosition> = {},
): PortfolioPosition {
  return position({
    sec_type: 'OPT',
    expiry: '20260619',
    strike: 200,
    right: 'C',
    quantity: 1,
    ...overrides,
  })
}

function position(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    account: 'DU1',
    symbol: 'AAPL',
    sec_type: 'STK',
    local_symbol: null,
    expiry: null,
    strike: null,
    right: null,
    multiplier: null,
    exchange: 'SMART',
    currency: 'USD',
    quantity: 0,
    average_cost: null,
    last_price: null,
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
    ...overrides,
  }
}

function draftLeg(overrides: Partial<DraftOptionLeg> = {}): DraftOptionLeg {
  return {
    ticker: 'AAPL',
    expiration: '2026-06-19',
    right: 'CALL',
    strike: 200,
    signedQuantity: 1,
    quote: 1.25,
    bid: 1.2,
    ask: 1.25,
    ...overrides,
  }
}

function optionStrategyRequest(
  overrides: Partial<OptionStrategyOrderRequest> = {},
): OptionStrategyOrderRequest {
  return {
    order_kind: 'option_strategy',
    account: 'DU1',
    limit_price: 1.25,
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
    ...overrides,
  }
}

function orderRecord({
  order_id,
  parent_order_id,
  request,
  status,
}: Pick<OrderRecord, 'order_id' | 'parent_order_id' | 'status'> & {
  request: OptionStrategyOrderRequest
}): OrderRecord {
  return {
    order_id,
    parent_order_id,
    perm_id: null,
    account: request.account,
    status,
    editable: true,
    filled: 0,
    remaining: 1,
    avg_fill_price: null,
    rejection_message: null,
    submitted_at: '2026-06-03T00:00:00Z',
    updated_at: '2026-06-03T00:00:00Z',
    preview: {
      preview_id: `preview-${order_id}`,
      account: request.account,
      order_kind: 'option_strategy',
      summary: 'BUY 1 AAPL 2026-06-19 200 CALL @ 1.25',
      time_in_force: 'DAY',
      estimated_order_type: 'LIMIT',
      request,
    },
  }
}
