import { describe, expect, it } from 'vitest'

import {
  mergeOptionQuoteSelection,
  type DraftOptionLeg,
} from '@/features/options/lib/strategyLegs'

const leg: DraftOptionLeg = {
  ticker: 'AAPL',
  expiration: '2026-06-19',
  right: 'CALL',
  strike: 200,
  signedQuantity: 1,
  quote: 1.25,
  bid: 1.2,
  ask: 1.25,
}

describe('strategyLegs', () => {
  it('adds buy asks as positive signed quantities', () => {
    expect(
      mergeOptionQuoteSelection([], {
        ticker: 'AAPL',
        expiration: '2026-06-19',
        right: 'CALL',
        strike: 200,
        action: 'BUY',
        quote: 1.25,
        bid: 1.2,
        ask: 1.25,
      }),
    ).toEqual([leg])
  })

  it('adds sell bids as negative signed quantities', () => {
    expect(
      mergeOptionQuoteSelection([], {
        ticker: 'AAPL',
        expiration: '2026-06-19',
        right: 'PUT',
        strike: 190,
        action: 'SELL',
        quote: 0.9,
        bid: 0.9,
        ask: 1,
      }),
    ).toEqual([
      {
        ticker: 'AAPL',
        expiration: '2026-06-19',
        right: 'PUT',
        strike: 190,
        signedQuantity: -1,
        quote: 0.9,
        bid: 0.9,
        ask: 1,
      },
    ])
  })

  it('merges duplicate legs and removes zero-net legs', () => {
    expect(
      mergeOptionQuoteSelection([leg], {
        ticker: 'AAPL',
        expiration: '2026-06-19',
        right: 'CALL',
        strike: 200,
        action: 'SELL',
        quote: 1.2,
        bid: 1.2,
        ask: 1.25,
      }),
    ).toEqual([])
  })
})
