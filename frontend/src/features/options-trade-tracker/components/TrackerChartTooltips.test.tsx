// @vitest-environment jsdom

import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MonthlyPerformanceChart } from './MonthlyPerformanceChart'
import { StrategyExecutionPieChart } from './StrategyExecutionPieChart'
import type { CompletedTradeProjection } from '../lib/tradeTracker'

const tooltip = vi.hoisted(() => ({ index: 4 }))

// Activate the real Recharts tooltip without relying on jsdom pointer geometry.
vi.mock('@/components/ui/chart', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ui/chart')>()
  return {
    ...original,
    ChartTooltip: (props: ComponentProps<typeof original.ChartTooltip>) => (
      <original.ChartTooltip {...props} active defaultIndex={tooltip.index} isAnimationActive={false} />
    ),
  }
})

afterEach(cleanup)
beforeEach(() => { tooltip.index = 4 })

function trade(strategy: string, pnl: number, size = -1): CompletedTradeProjection {
  return { pnl, row: {
    id: `${strategy}-${pnl}`, display_order: 1, status: 'Completed', strategy,
    ticker: 'SYN', month: 'may', size, strike_price: 100, credit_debit: 5, exit: 2,
    created_at: '', updated_at: '',
  } }
}

function activeTooltip(container: HTMLElement) {
  return container.querySelector<HTMLElement>('.recharts-tooltip-wrapper')
}

describe('tracker chart tooltips', () => {
  it('shows the month and named signed values for multiple strategies', async () => {
    const completedTrades = [trade('CC', 4035), trade('CUSTOM / RATIO SPREAD', -610), trade('CSP', 0), trade('LEAPS', 1234567.89)]
    const { container } = render(<MonthlyPerformanceChart completedTrades={completedTrades} strategyOptions={[]} />)
    await waitFor(() => expect(activeTooltip(container)?.textContent).toContain('-$610.00'))
    const text = activeTooltip(container)!.textContent
    for (const value of ['May', 'CC', '$4,035.00', 'CUSTOM / RATIO SPREAD', 'CSP', '$0.00', 'LEAPS', '$1,234,567.89']) expect(text).toContain(value)
    expect(text).not.toMatch(/strategy_\d+/)
    expect(activeTooltip(container)!.querySelectorAll('[style*="--color-bg"]')).toHaveLength(4)
  })

  it('shows a single strategy and identifies the Net P&L when switching modes', async () => {
    const { container } = render(<MonthlyPerformanceChart completedTrades={[trade('IRON CONDOR', -610)]} strategyOptions={[]} />)
    await waitFor(() => expect(activeTooltip(container)?.textContent).toContain('IRON CONDOR'))
    expect(activeTooltip(container)!.textContent).toContain('May')
    fireEvent.click(screen.getByRole('radio', { name: 'Net' }))
    await waitFor(() => expect(activeTooltip(container)?.textContent).toContain('Net P&L'))
    expect(activeTooltip(container)!.textContent).toContain('May')
    expect(activeTooltip(container)!.textContent).toContain('-$610.00')
  })

  it('shows the pie strategy with execution counts summed from absolute sizes', async () => {
    tooltip.index = 0
    const { container } = render(<StrategyExecutionPieChart completedTrades={[trade('IRON CONDOR', 100, -12000), trade('IRON CONDOR', -20, 345)]} />)
    await waitFor(() => expect(activeTooltip(container)?.textContent).toContain('12,345'))
    expect(activeTooltip(container)!.textContent).toContain('IRON CONDOR')
    expect(activeTooltip(container)!.textContent).not.toMatch(/strategy_\d+/)
    expect(activeTooltip(container)!.querySelectorAll('[style*="--color-bg"]')).toHaveLength(1)
    expect(container.querySelector('.recharts-legend-wrapper')?.textContent).toContain('IRON CONDOR')
  })
})
