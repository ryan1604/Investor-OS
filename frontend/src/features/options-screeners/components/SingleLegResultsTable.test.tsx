// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  SingleLegResultsTable,
  type SingleLegColumn,
} from '@/features/options-screeners/components/SingleLegResultsTable'
import type { CashSecuredPutCandidate, CoveredCallCandidate } from '@/api/optionsScreeners'
import {
  formatScreenerPercentage,
} from '@/features/options-screeners/lib/screenerResults'

const virtualCount = vi.hoisted(() => vi.fn())

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => {
    virtualCount(count)
    return {
      getTotalSize: () => count * 43,
      getVirtualItems: () =>
        Array.from({ length: Math.min(count, 12) }, (_, index) => ({
          index,
          key: index,
          size: 43,
          start: index * 43,
        })),
    }
  },
}))

afterEach(() => {
  cleanup()
  virtualCount.mockClear()
  vi.restoreAllMocks()
})

const discountColumn: SingleLegColumn<CashSecuredPutCandidate> = {
  key: 'discount_percentage',
  label: 'Discount %',
  render: (row) => formatScreenerPercentage(row.discount_percentage),
}

const gainColumn: SingleLegColumn<CoveredCallCandidate> = {
  key: 'gain_percentage',
  label: 'Gain %',
  render: (row) => formatScreenerPercentage(row.gain_percentage),
}

describe('SingleLegResultsTable', () => {
  it('renders CSP rows, sorts columns, and supports keyboard activation', () => {
    const onActivate = vi.fn()
    const onSort = vi.fn()
    render(
      <SingleLegResultsTable
        candidates={[cspCandidate('MSFT', 10), cspCandidate('AAPL', 20)]}
        finalColumn={discountColumn}
        sort={{ key: 'annualized_return', direction: 'desc' }}
        onSort={onSort}
        onActivate={onActivate}
      />,
    )

    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(rows[1].textContent).toContain('AAPL')

    fireEvent.click(screen.getByRole('button', { name: /Ticker/ }))
    expect(onSort).toHaveBeenCalledWith('ticker')

    fireEvent.keyDown(rows[1], { key: 'Enter' })
    expect(onActivate).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: 'AAPL' }),
    )
  })

  it('renders CC-specific gain column behavior', () => {
    const onSort = vi.fn()
    render(
      <SingleLegResultsTable
        candidates={[ccCandidate('MSFT', 10), ccCandidate('AAPL', 20)]}
        finalColumn={gainColumn}
        sort={{ key: 'annualized_return', direction: 'desc' }}
        onSort={onSort}
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
    expect(screen.getAllByRole('row')[1].textContent).toContain('15.00%')

    fireEvent.click(screen.getByRole('button', { name: /Gain %/ }))
    expect(onSort).toHaveBeenCalledWith('gain_percentage')
  })

  it('does not activate a row while text is selected', () => {
    const onActivate = vi.fn()
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => 'selected value',
    } as Selection)
    render(
      <SingleLegResultsTable
        candidates={[cspCandidate('AAPL', 20)]}
        finalColumn={discountColumn}
        sort={{ key: 'annualized_return', direction: 'desc' }}
        onSort={vi.fn()}
        onActivate={onActivate}
      />,
    )

    fireEvent.click(screen.getAllByRole('row')[1])
    expect(onActivate).not.toHaveBeenCalled()
  })

  it('virtualizes a deterministic 500-row completed result set', () => {
    const candidates = Array.from({ length: 500 }, (_, index) =>
      cspCandidate(`T${String(index).padStart(3, '0')}`, 500 - index),
    )

    render(
      <SingleLegResultsTable
        candidates={candidates}
        finalColumn={discountColumn}
        sort={{ key: 'annualized_return', direction: 'desc' }}
        onSort={vi.fn()}
      />,
    )

    expect(virtualCount).toHaveBeenCalledWith(500)
    expect(screen.getAllByRole('row')).toHaveLength(13)
    expect(screen.getByText('T000')).toBeTruthy()
    expect(screen.queryByText('T499')).toBeNull()
  })
})

function cspCandidate(
  ticker: string,
  annualizedReturn: number,
): CashSecuredPutCandidate {
  return {
    strategy: 'csp',
    ticker,
    annualized_return: annualizedReturn,
    stock_price: 110,
    strike: 100,
    expiration: '2026-07-17',
    dte: 30,
    delta: -0.2,
    bid: 1,
    ask: 1.2,
    discount_percentage: 9.09,
    contract: { con_id: annualizedReturn, local_symbol: `${ticker} PUT` },
  }
}

function ccCandidate(
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
