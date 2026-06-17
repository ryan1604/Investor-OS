// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CspResultsTable } from '@/features/options-screeners/components/CspResultsTable'
import type { CashSecuredPutCandidate } from '@/features/options-screeners/lib/screenerResults'

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
})

describe('CspResultsTable', () => {
  it('renders virtualized rows, sorts columns, and supports keyboard activation', () => {
    const onActivate = vi.fn()
    const onSort = vi.fn()
    render(
      <CspResultsTable
        candidates={[candidate('MSFT', 10), candidate('AAPL', 20)]}
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

  it('does not activate a row while text is selected', () => {
    const onActivate = vi.fn()
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => 'selected value',
    } as Selection)
    render(
      <CspResultsTable
        candidates={[candidate('AAPL', 20)]}
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
      candidate(`T${String(index).padStart(3, '0')}`, 500 - index),
    )

    render(
      <CspResultsTable
        candidates={candidates}
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

function candidate(
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
