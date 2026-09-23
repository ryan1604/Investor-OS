// @vitest-environment jsdom

import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MonthlyPerformanceChart } from './MonthlyPerformanceChart'
import type { CompletedTradeProjection } from '../lib/tradeTracker'

// Render real Recharts geometry at its final position, without animation timing.
vi.mock('recharts', async (importOriginal) => {
  const original = await importOriginal<typeof import('recharts')>()
  return {
    ...original,
    Bar: (props: ComponentProps<typeof original.Bar>) => <original.Bar {...props} isAnimationActive={false} />,
  }
})

afterEach(cleanup)

function trades(values: number[]): CompletedTradeProjection[] {
  return values.map((pnl, index) => ({ pnl, row: {
    id: `row-${index}`, display_order: index + 1, status: 'Completed', strategy: `STRATEGY ${index + 1}`,
    ticker: 'SYN', month: 'may', expiry_date: null, size: -1, strike_price: 100, credit_debit: 5, exit: 2,
    created_at: '', updated_at: '',
  } }))
}

function numericTick(text: string) {
  return Number(text.replace(/[$,k]/g, '')) * (text.endsWith('k') ? 1000 : 1)
}

function chartScale(container: HTMLElement) {
  const ticks = [...container.querySelectorAll('.recharts-yAxis-tick-labels text')].map((tick) => ({
    value: numericTick(tick.textContent ?? ''), y: Number(tick.getAttribute('y')),
  }))
  const zero = ticks.find((tick) => tick.value === 0)!
  const nonzero = ticks.find((tick) => tick.value !== 0)!
  expect(zero).toBeDefined()
  expect(nonzero).toBeDefined()
  const pixelsPerDollar = (zero.y - nonzero.y) / nonzero.value
  return { zero: zero.y, pixelsPerDollar, top: Math.min(...ticks.map((tick) => tick.y)), bottom: Math.max(...ticks.map((tick) => tick.y)) }
}

async function expectStacks(container: HTMLElement, values: number[]) {
  await waitFor(() => {
    expect(container.querySelectorAll('.recharts-bar-rectangle path')).toHaveLength(values.filter((value) => value !== 0).length)
    const scale = chartScale(container)
    const netMode = screen.getByRole('radio', { name: 'Net' }).getAttribute('aria-checked') === 'true'
    let positive = 0
    let negative = 0
    values.forEach((value, index) => {
      const bar = [...container.querySelectorAll('.recharts-bar-rectangle path')].find((path) => path.getAttribute('name') === (netMode ? 'Net P&L' : `STRATEGY ${index + 1}`))
      if (value === 0) {
        expect(bar).toBeUndefined()
        return
      }
      expect(bar).toBeTruthy()
      const start = value > 0 ? positive : negative
      const end = start + value
      const expectedTop = scale.zero - Math.max(start, end) * scale.pixelsPerDollar
      const expectedHeight = Math.abs(value) * scale.pixelsPerDollar
      const rawY = Number(bar!.getAttribute('y'))
      const rawHeight = Number(bar!.getAttribute('height'))
      const y = Math.min(rawY, rawY + rawHeight)
      const height = Math.abs(rawHeight)
      expect(y).toBeCloseTo(expectedTop, 3)
      expect(height).toBeCloseTo(expectedHeight, 3)
      expect(height).toBeGreaterThan(0)
      expect(y).toBeGreaterThanOrEqual(scale.top - 0.001)
      expect(y + height).toBeLessThanOrEqual(scale.bottom + 0.001)
      if (value > 0) positive = end
      else negative = end
    })
    // Every visible rectangle belongs to May; zero and empty months have no shape.
    const mayTick = [...container.querySelectorAll('.recharts-xAxis-tick-labels text')].find((tick) => tick.textContent === 'May')!
    for (const bar of container.querySelectorAll('.recharts-bar-rectangle path')) {
      expect(Math.abs(Number(bar.getAttribute('x')) + Number(bar.getAttribute('width')) / 2 - Number(mayTick.getAttribute('x')))).toBeLessThan(1)
      expect(bar.getAttribute('d')).not.toMatch(/[aA]/)
    }
    const baseline = container.querySelector('.recharts-reference-line line')
    expect(baseline).toBeTruthy()
    expect(Number(baseline!.getAttribute('y1'))).toBeCloseTo(scale.zero, 5)
    expect(Number(baseline!.getAttribute('y2'))).toBeCloseTo(scale.zero, 5)
  })
}

describe('monthly performance signed geometry', () => {
  it.each([
    [1200, -400, 1200],
    [-400, 1200, 1200],
    [1200, 1200, -400],
    [-1200, -400, -1200],
    [1200, 400, 1200],
    [1200, -1200, 0],
  ])('renders [%i, %i, %i] with independent positive and negative stacks', async (...values) => {
    const { container } = render(<MonthlyPerformanceChart completedTrades={trades(values)} strategyOptions={[]} />)
    await expectStacks(container, values)
    fireEvent.click(screen.getByRole('radio', { name: 'Net' }))
    await expectStacks(container, [values.reduce((sum, value) => sum + value, 0)])
  })

  it('renders a zero baseline and no visible bars for completed zero-P&L trades', async () => {
    const { container } = render(<MonthlyPerformanceChart completedTrades={trades([0, 0])} strategyOptions={[]} />)
    await expectStacks(container, [0, 0])
    fireEvent.click(screen.getByRole('radio', { name: 'Net' }))
    await expectStacks(container, [0])
  })

  it('formats compact negative ticks with the sign before the currency symbol', async () => {
    const { container } = render(<MonthlyPerformanceChart completedTrades={trades([-4000])} strategyOptions={[]} />)
    await waitFor(() => expect(container.querySelector('.recharts-yAxis-tick-labels')?.textContent).toContain('-$4k'))
    expect(container.querySelector('.recharts-yAxis-tick-labels')?.textContent).not.toContain('$-')
  })

  it('retains the empty state when no completed valid trades exist', () => {
    const { container } = render(<MonthlyPerformanceChart completedTrades={[]} strategyOptions={['CSP']} />)
    expect(screen.getByText('Complete valid trades to chart monthly performance.')).toBeTruthy()
    expect(container.querySelector('.recharts-surface')).toBeNull()
  })
})
