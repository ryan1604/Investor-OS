// @vitest-environment jsdom

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { StrategyExecutionPieChart } from './StrategyExecutionPieChart'
import type { CompletedTradeProjection } from '../lib/tradeTracker'

const trades: CompletedTradeProjection[] = ['CC', 'CUSTOM / RATIO SPREAD'].map((strategy, index) => ({
  pnl: 0, row: { id: `row-${index}`, display_order: index + 1, status: 'Completed', strategy,
    ticker: 'SYN', month: 'may', size: -(index + 1), strike_price: 100, credit_debit: 0.02, exit: 0, created_at: '', updated_at: '' },
}))

beforeEach(() => {
  const original = HTMLElement.prototype.getBoundingClientRect
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.classList.contains('recharts-tooltip-wrapper')) {
      // jsdom has no layout: measure only nonempty tooltip content, including
      // visibility:hidden, which browsers still lay out at its normal size.
      return new DOMRect(0, 0, this.textContent ? this.textContent.length * 7 + 32 : 0, this.textContent ? 32 : 0)
    }
    return original.call(this)
  })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function chart() {
  const result = render(<StrategyExecutionPieChart completedTrades={trades} />)
  await waitFor(() => expect(result.container.querySelectorAll('.recharts-pie-sector')).toHaveLength(2))
  const sectors = result.container.querySelectorAll('.recharts-pie-sector')
  const tooltip = result.container.querySelector<HTMLElement>('.recharts-tooltip-wrapper')!
  return { ...result, sectors, tooltip }
}

describe('pie tooltip lifecycle in Recharts', () => {
  it('keeps the first sector and its geometry stable through an immediate hover and exit', async () => {
    const { container, sectors, tooltip } = await chart()
    const first = sectors[0].querySelector('path')!
    const shape = first.getAttribute('d')
    expect(shape).toMatch(/A/)
    fireEvent.mouseEnter(sectors[0])
    await waitFor(() => expect(tooltip.textContent).toBe('CC1'))
    fireEvent.mouseLeave(sectors[0])
    await waitFor(() => expect(tooltip.style.visibility).toBe('hidden'))
    expect(container.querySelector('.recharts-pie-sector path')).toBe(first)
    expect(first.getAttribute('d')).toBe(shape)
  })

  it('retains wrapper dimensions and transform through an inactive gap', async () => {
    const { container, sectors, tooltip } = await chart()
    expect(tooltip.textContent).toBe('')
    fireEvent.mouseEnter(sectors[0])
    await waitFor(() => expect(tooltip.style.visibility).toBe('visible'))
    expect(tooltip.textContent).toBe('CC1')
    const transform = tooltip.style.transform
    expect(transform).toMatch(/^translate\(/)
    fireEvent.mouseLeave(sectors[0])
    await waitFor(() => expect(tooltip.style.visibility).toBe('hidden'))
    expect(tooltip.getBoundingClientRect().width).toBeGreaterThan(0)
    expect(tooltip.style.transform).toBe(transform)
    expect(tooltip.style.pointerEvents).toBe('none')
    fireEvent.mouseEnter(sectors[1])
    await waitFor(() => expect(tooltip.textContent).toBe('CUSTOM / RATIO SPREAD2'))
    expect(tooltip.style.visibility).toBe('visible')
    expect(tooltip.style.transform).not.toBe(transform)
    expect(container.querySelector('.recharts-tooltip-wrapper')).toBe(tooltip)
  })

  it('allows Escape dismissal and resumes at a different segment', async () => {
    const { sectors, tooltip } = await chart()
    fireEvent.mouseEnter(sectors[0])
    await waitFor(() => expect(tooltip.style.visibility).toBe('visible'))
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(tooltip.style.visibility).toBe('hidden'))
    expect(tooltip.textContent).toBe('CC1')
    fireEvent.mouseLeave(sectors[0])
    fireEvent.mouseEnter(sectors[1])
    await waitFor(() => expect(tooltip.style.visibility).toBe('visible'))
    expect(tooltip.textContent).toBe('CUSTOM / RATIO SPREAD2')
  })

  it('clears hidden content when chart data changes and unmounts it for empty data', async () => {
    const { container, sectors, tooltip, rerender } = await chart()
    fireEvent.mouseEnter(sectors[0])
    await waitFor(() => expect(tooltip.textContent).toBe('CC1'))
    fireEvent.mouseLeave(sectors[0])
    const updated = [{ ...trades[0], row: { ...trades[0].row, size: -10 } }, trades[1]]
    rerender(<StrategyExecutionPieChart completedTrades={updated} />)
    await waitFor(() => expect(tooltip.textContent).toBe(''))
    expect(tooltip.style.visibility).toBe('hidden')
    expect(tooltip.getBoundingClientRect().width).toBe(0)
    fireEvent.mouseEnter(container.querySelectorAll('.recharts-pie-sector')[0])
    await waitFor(() => expect(tooltip.textContent).toBe('CC10'))
    rerender(<StrategyExecutionPieChart completedTrades={[]} />)
    expect(container.querySelector('.recharts-tooltip-wrapper')).toBeNull()
  })

  it('preserves the library reduced-motion setting', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    const { sectors, tooltip } = await chart()
    fireEvent.mouseEnter(sectors[0])
    await waitFor(() => expect(tooltip.style.visibility).toBe('visible'))
    expect(tooltip.style.transition).toBe('')
    fireEvent.mouseLeave(sectors[0])
    fireEvent.mouseEnter(sectors[1])
    await waitFor(() => expect(tooltip.textContent).toBe('CUSTOM / RATIO SPREAD2'))
    expect(tooltip.style.transition).toBe('')
  })
})
