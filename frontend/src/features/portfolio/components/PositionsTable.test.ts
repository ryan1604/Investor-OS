import { describe, expect, it } from 'vitest'

import {
  positionKeys,
  type DisplayPosition,
} from '@/features/portfolio/lib/positions'

function displayPosition(
  overrides: Partial<DisplayPosition> = {},
): DisplayPosition {
  return {
    account: 'DU123',
    symbol: 'AAPL',
    sec_type: 'STK',
    local_symbol: null,
    expiry: null,
    strike: null,
    right: null,
    multiplier: null,
    exchange: 'SMART',
    currency: 'USD',
    quantity: 1,
    average_cost: 100,
    last_price: 110,
    change_percent: 1,
    pnl: 10,
    pnl_percent: 10,
    unrealized_pnl: 10,
    unrealized_pnl_percent: 10,
    market_value: 110,
    cost_basis: 100,
    average_price: 100,
    net_liquidity: 1_000,
    net_liquidity_percent: 11,
    instrumentTitle: 'AAPL',
    instrumentDetail: null,
    ...overrides,
  }
}

describe('positionKeys', () => {
  it('keeps the same key for a position when row order changes', () => {
    const apple = displayPosition({
      symbol: 'AAPL',
      instrumentTitle: 'AAPL',
      quantity: 1,
    })
    const microsoft = displayPosition({
      symbol: 'MSFT',
      instrumentTitle: 'MSFT',
      quantity: 2,
    })

    const [appleKey, microsoftKey] = positionKeys([apple, microsoft])
    const [reorderedMicrosoftKey, reorderedAppleKey] = positionKeys([
      microsoft,
      apple,
    ])

    expect(reorderedAppleKey).toBe(appleKey)
    expect(reorderedMicrosoftKey).toBe(microsoftKey)
  })

  it('returns distinct keys for duplicate position identities', () => {
    const duplicate = displayPosition()
    const keys = positionKeys([
      duplicate,
      { ...duplicate, quantity: 2, pnl: 20 },
    ])

    expect(new Set(keys).size).toBe(2)
    expect(keys[1]).toBe(`${keys[0]}-1`)
  })
})
