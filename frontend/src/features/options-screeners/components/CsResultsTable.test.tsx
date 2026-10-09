// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CsResultsTable } from '@/features/options-screeners/components/CsResultsTable'
import type { CreditSpreadCandidate } from '@/api/optionsScreeners'

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 43,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        size: 43,
        start: index * 43,
      })),
  }),
}))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CsResultsTable', () => {
  it('uses distinct row keys for multiple widths sharing a short contract', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    render(
      <CsResultsTable
        candidates={[candidate(90, 2), candidate(93, 3)]}
        sort={{ key: 'long_strike', direction: 'asc' }}
        onSort={vi.fn()}
      />,
    )

    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.getByText('90.00')).toBeTruthy()
    expect(screen.getByText('93.00')).toBeTruthy()
    expect(consoleError.mock.calls.flat().join('\n')).not.toContain(
      'Encountered two children with the same key',
    )
  })
})

function candidate(longStrike: number, longConId: number): CreditSpreadCandidate {
  return {
    strategy: 'put_credit_spread',
    ticker: 'AAPL',
    annualized_return: 10,
    stock_price: 100,
    short_strike: 95,
    long_strike: longStrike,
    expiration: '2026-07-17',
    dte: 30,
    short_delta: -0.2,
    net_bid: 1,
    net_ask: 1.2,
    distance_percentage: 5,
    short_contract: { con_id: 1, local_symbol: 'AAPL SHORT' },
    long_contract: { con_id: longConId, local_symbol: `AAPL ${longStrike}P` },
  }
}
