import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  CreditSpreadCandidate,
  OptionsScreenerFilters,
  OptionsScreenerSpreadQuoteRefreshResponse,
} from '@/api/optionsScreeners'
import { refreshedCandidateWarning } from '@/features/options-screeners/lib/refreshedCandidateWarning'
import { singleLegRefreshedContractWarning } from '@/features/options-screeners/lib/singleLegWarnings'

const filters: OptionsScreenerFilters = {
  version: 1,
  minimum_dte: 30,
  maximum_dte: 30,
  minimum_absolute_delta: 0.15,
  maximum_absolute_delta: 0.3,
  minimum_annualized_return: 10,
}
const refreshed: OptionsScreenerSpreadQuoteRefreshResponse = {
  strategy: 'put_credit_spread',
  ticker: 'TSLA',
  expiration: '2026-07-31',
  right: 'PUT',
  short_strike: 95,
  long_strike: 90,
  short_contract: { con_id: 1, local_symbol: 'SHORT PUT' },
  long_contract: { con_id: 2, local_symbol: 'LONG PUT' },
  short_bid: 2.1,
  short_ask: 2.3,
  short_midpoint: 2.2,
  long_bid: 0.9,
  long_ask: 1,
  long_midpoint: 0.95,
  short_delta: -0.2,
  net_bid: 1.1,
  net_ask: 1.4,
  net_midpoint: 1.25,
  maximum_loss: 3.75,
  refreshed_at: '2026-07-01T16:00:00Z',
}
const candidate: CreditSpreadCandidate = {
  ...refreshed,
  short_delta: -0.2,
  annualized_return: 40,
  stock_price: 100,
  dte: 30,
  distance_percentage: 5,
}
const warning = 'The refreshed spread no longer satisfies the current CS scan filters, exact width, or maximum-loss rules.'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-07-01T16:00:00Z'))
})
afterEach(() => vi.useRealTimers())

describe('refreshed candidate warnings', () => {
  it('accepts both signs of short delta at the inclusive absolute-delta boundaries', () => {
    for (const short_delta of [-0.15, 0.15, -0.3, 0.3]) {
      expect(refreshedCandidateWarning({ ...refreshed, short_delta }, candidate, filters)).toBeNull()
    }
  })

  it('keeps the exact CS warning for missing or out-of-range short deltas', () => {
    for (const short_delta of [null, -0.149, 0.301]) {
      expect(refreshedCandidateWarning({ ...refreshed, short_delta }, candidate, filters)).toBe(warning)
    }
  })

  it('keeps DTE and annualized-return thresholds inclusive', () => {
    const annualizedReturn = (1.25 / 3.75) * (365 / 30) * 100
    expect(refreshedCandidateWarning(refreshed, candidate, {
      ...filters, minimum_annualized_return: annualizedReturn,
    })).toBeNull()
    expect(refreshedCandidateWarning(refreshed, candidate, {
      ...filters, minimum_annualized_return: annualizedReturn + 0.01,
    })).toBe(warning)
    for (const expiration of ['2026-07-30', '2026-08-01']) {
      expect(refreshedCandidateWarning({ ...refreshed, expiration }, candidate, filters)).toBe(warning)
    }
  })

  it('retains exact-width tolerance, positive net credit below width, and positive maximum loss', () => {
    expect(refreshedCandidateWarning({ ...refreshed, long_strike: 90 + 0.5e-6 }, candidate, filters)).toBeNull()
    for (const change of [
      { long_strike: 89 },
      { net_midpoint: 0 },
      { net_midpoint: 5 },
      { maximum_loss: 0 },
    ]) {
      expect(refreshedCandidateWarning({ ...refreshed, ...change }, candidate, filters)).toBe(warning)
    }
  })

  it('keeps single-leg absolute delta and the distinct CSP/CC return denominators', () => {
    const quote = {
      ticker: 'TSLA', expiration: '2026-07-31', strike: 95, right: 'PUT' as const,
      contract: refreshed.short_contract, bid: 0.9, ask: 1.1, midpoint: 1,
      delta: -0.2, refreshed_at: refreshed.refreshed_at,
    }
    const args = { refreshed: quote, filters: { ...filters, minimum_annualized_return: 12.5 }, message: 'single-leg warning' }
    expect(singleLegRefreshedContractWarning({ ...args, annualizedReturnDenominator: 95 })).toBeNull()
    expect(singleLegRefreshedContractWarning({ ...args, annualizedReturnDenominator: 100 })).toBe('single-leg warning')
    expect(singleLegRefreshedContractWarning({ ...args, annualizedReturnDenominator: 0 })).toBe('single-leg warning')
    expect(singleLegRefreshedContractWarning({ ...args, refreshed: { ...quote, delta: null }, annualizedReturnDenominator: 95 })).toBe('single-leg warning')
  })
})
