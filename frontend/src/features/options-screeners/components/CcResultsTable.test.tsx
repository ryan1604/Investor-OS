// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CcResultsTable } from '@/features/options-screeners/components/CcResultsTable'
import type { CoveredCallCandidate } from '@/features/options-screeners/lib/screenerResults'

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

afterEach(cleanup)

describe('CcResultsTable', () => {
  it('renders the fixed gain columns, sorts, and supports keyboard activation', () => {
    const onActivate = vi.fn()
    const onSort = vi.fn()
    render(
      <CcResultsTable
        candidates={[candidate('MSFT', 10), candidate('AAPL', 20)]}
        sort={{ key: 'annualized_return', direction: 'desc' }}
        onSort={onSort}
        onActivate={onActivate}
      />,
    )

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      expect.stringContaining('Ticker'),
      expect.stringContaining('Annualized Return %'),
      expect.stringContaining('Stock Price'),
      expect.stringContaining('Strike'),
      expect.stringContaining('Expiration'),
      expect.stringContaining('DTE'),
      expect.stringContaining('Delta'),
      expect.stringContaining('Bid'),
      expect.stringContaining('Ask'),
      expect.stringContaining('Gain %'),
    ])
    const rows = screen.getAllByRole('row')
    expect(rows[1].textContent).toContain('AAPL')
    expect(rows[1].textContent).toContain('15.00%')

    fireEvent.click(screen.getByRole('button', { name: /Gain %/ }))
    expect(onSort).toHaveBeenCalledWith('gain_percentage')

    fireEvent.keyDown(rows[1], { key: 'Enter' })
    expect(onActivate).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: 'AAPL' }),
    )
  })
})

function candidate(
  ticker: string,
  annualizedReturn: number,
): CoveredCallCandidate {
  return {
    strategy: 'cc',
    ticker,
    annualized_return: annualizedReturn,
    stock_price: 100,
    strike: 115,
    expiration: '2026-07-17',
    dte: 30,
    delta: 0.2,
    bid: 1,
    ask: 1.2,
    gain_percentage: 15,
    contract: { con_id: annualizedReturn, local_symbol: `${ticker} CALL` },
  }
}
