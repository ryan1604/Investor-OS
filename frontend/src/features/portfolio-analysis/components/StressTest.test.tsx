// @vitest-environment jsdom

import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  StressGridTable,
  StressSummaryCards,
} from '@/features/portfolio-analysis/components/StressTest'
import { stressGrid } from '@/features/portfolio-analysis/testFixtures'

afterEach(cleanup)

function cellLabels(container: HTMLElement, attribute: string) {
  return Array.from(container.querySelectorAll(`td[${attribute}]`)).map((cell) => {
    const row = cell.closest('tr') as HTMLElement
    const table = cell.closest('table') as HTMLElement
    const column = Array.from(row.children).indexOf(cell)
    const header = table.querySelectorAll('thead th')[column]
    return `${row.querySelector('th')?.textContent} | ${header.textContent}`
  })
}

describe('StressGridTable', () => {
  it('renders every SPY move and IV shock with P&L in dollars and percent', () => {
    render(<StressGridTable stress={stressGrid()} />)

    expect(screen.getByText('Stress Test (Estimates)')).toBeTruthy()
    const [grid] = screen.getAllByRole('table')
    const headers = within(grid).getAllByRole('columnheader').map((cell) => cell.textContent)
    expect(headers).toEqual(['SPY Move', 'IV 0%', 'IV +25%', 'IV +50%', 'IV +100%'])
    const rows = within(grid).getAllByRole('rowheader').map((cell) => cell.textContent)
    expect(rows).toEqual(['-30%', '-20%', '-15%', '-10%', '-5%', '0%', '+5%', '+10%'])

    const down10 = within(grid).getAllByRole('row')[4]
    const values = within(down10).getAllByRole('cell').map((cell) => cell.textContent)
    expect(values).toEqual([
      '-$10,000-10.00%',
      '-$12,500-12.50%',
      '-$15,000-15.00%',
      '-$20,000-20.00%',
    ])
    expect(
      screen.getByText(
        '1 leg(s) are left out because their strategy group has a leg without a price or IV.',
        { exact: false },
      ),
    ).toBeTruthy()
  })

  it('marks margin-call cells red and highlights the realistic path', () => {
    const { container } = render(<StressGridTable stress={stressGrid()} />)

    expect(cellLabels(container, 'data-margin-call')).toEqual([
      '-30% | IV 0%',
      '-30% | IV +25%',
      '-30% | IV +50%',
      '-30% | IV +100%',
      'P&L | SPY -30% / IV +100%',
    ])
    for (const cell of container.querySelectorAll('td[data-margin-call]')) {
      expect(cell.className).toContain('bg-red-500/15')
    }
    expect(cellLabels(container, 'data-realistic-path')).toEqual([
      '-30% | IV +100%',
      'P&L | SPY -5% / IV +15%',
      'P&L | SPY -10% / IV +40%',
      'P&L | SPY -20% / IV +80%',
      'P&L | SPY -30% / IV +100%',
    ])
    const path = screen.getByRole('table', { name: 'Realistic path' })
    expect(within(path).getByText('-$28,000')).toBeTruthy()
  })
})

describe('StressSummaryCards', () => {
  it('shows the realistic -20% P&L and distance to margin call as estimates', () => {
    render(<StressSummaryCards stress={stressGrid()} />)

    expect(screen.getByText('Realistic -20% P&L (Est.)').parentElement?.textContent).toBe(
      'Realistic -20% P&L (Est.)-28.00%-$28,000',
    )
    expect(screen.getByText('21.4%')).toBeTruthy()
    expect(screen.getByText('SPY drop')).toBeTruthy()
    const note = screen.getByRole('img', { name: /calibration factor 1\.25/ })
    expect(note.getAttribute('title')).toBe(
      'Estimate: the SPY drop along the realistic path at which excess liquidity reaches zero. ' +
        'Reg T model margin $16,000 x calibration factor 1.25 (IB maintenance margin $20,000). ' +
        '1 strategy group(s) without prices add no P&L or margin.',
    )
    expect(screen.getByRole('img', { name: /SPY -20% with IV \+80%/ })).toBeTruthy()
  })

  it('shows "> 30%" when no margin call happens within the path', () => {
    const base = stressGrid()
    render(
      <StressSummaryCards
        stress={{
          ...base,
          margin: {
            ...base.margin,
            distance_to_margin_call_percent: null,
            margin_call_beyond_path: true,
          },
        }}
      />,
    )

    expect(screen.getByText('> 30%')).toBeTruthy()
    expect(screen.queryByText('SPY drop')).toBeNull()
  })

  it('shows "-" without net liquidation', () => {
    const base = stressGrid()
    render(
      <StressSummaryCards
        stress={{
          ...base,
          realistic_path: base.realistic_path.map((cell) => ({ ...cell, pnl_percent: null })),
          margin: { ...base.margin, distance_to_margin_call_percent: null },
        }}
      />,
    )

    const distance = screen.getByText('Distance to Margin Call (Est.)').parentElement
    expect(distance?.textContent).toBe('Distance to Margin Call (Est.)-')
  })
})
