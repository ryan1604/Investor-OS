// @vitest-environment jsdom

import type { ComponentProps } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ChartContainer, ChartTooltipContent, type ChartConfig } from './chart'
import { formatCurrency } from '@/lib/format'

afterEach(cleanup)

function renderTooltip(props: ComponentProps<typeof ChartTooltipContent>, config: ChartConfig = {}) {
  return render(
    <ChartContainer config={config}>
      <div><ChartTooltipContent {...props} /></div>
    </ChartContainer>,
  )
}

function indicatorFor(label: string) {
  return screen.getByText(label).parentElement?.parentElement?.parentElement?.querySelector<HTMLElement>('[style]')
}

describe('ChartTooltipContent', () => {
  it('formats only values while retaining the heading, configured names, and matching indicators', () => {
    const valueFormatter = vi.fn((value) => formatCurrency(Number(value)))
    renderTooltip({
      active: true,
      label: 'May',
      nameKey: 'dataKey',
      valueFormatter,
      payload: [
        { graphicalItemId: 'bar-0', dataKey: 'strategy_0', name: 'strategy_0', value: -610, color: 'red' },
        { graphicalItemId: 'bar-1', dataKey: 'strategy_1', name: 'strategy_1', value: 0, color: 'blue' },
        { graphicalItemId: 'bar-2', dataKey: 'strategy_2', name: 'strategy_2', value: 1234567.89, color: 'green' },
      ],
    }, {
      strategy_0: { label: 'IRON CONDOR' },
      strategy_1: { label: 'CSP' },
      strategy_2: { label: 'CUSTOM / RATIO SPREAD' },
    })

    expect(screen.getByText('May')).toBeTruthy()
    expect(screen.getByText('-$610.00')).toBeTruthy()
    expect(screen.getByText('$0.00')).toBeTruthy()
    expect(screen.getByText('$1,234,567.89')).toBeTruthy()
    expect(screen.queryByText(/^strategy_\d+$/)).toBeNull()
    expect(indicatorFor('IRON CONDOR')?.style.getPropertyValue('--color-bg')).toBe('red')
    expect(indicatorFor('CSP')?.style.getPropertyValue('--color-bg')).toBe('blue')
    expect(indicatorFor('CUSTOM / RATIO SPREAD')?.style.getPropertyValue('--color-bg')).toBe('green')
    expect(valueFormatter.mock.calls.map(([value]) => value)).toEqual([-610, 0, 1234567.89])
  })

  it('falls back to the readable series name if its configuration is missing', () => {
    renderTooltip({
      active: true, nameKey: 'dataKey', valueFormatter: (value) => `${value} trades`,
      payload: [{ graphicalItemId: 'bar-0', dataKey: 'strategy_0', name: 'CUSTOM STRATEGY', value: 7, color: 'purple' }],
    })
    expect(screen.getByText('CUSTOM STRATEGY')).toBeTruthy()
    expect(screen.getByText('7 trades')).toBeTruthy()
    expect(screen.queryByText('strategy_0')).toBeNull()
  })

  it('resolves pie labels from the nested payload and retains its fill indicator', () => {
    renderTooltip({
      active: true, hideLabel: true, nameKey: 'strategyKey',
      valueFormatter: (value) => Number(value).toLocaleString('en-US'),
      payload: [{
        graphicalItemId: 'pie', dataKey: 'count', name: 'IRON CONDOR', value: 12345,
        payload: { strategyKey: 'strategy_0', fill: 'orange' },
      }],
    }, { strategy_0: { label: 'IRON CONDOR' } })
    expect(screen.getAllByText('IRON CONDOR')).toHaveLength(1)
    expect(screen.getByText('12,345')).toBeTruthy()
    expect(indicatorFor('IRON CONDOR')?.style.getPropertyValue('--color-bg')).toBe('orange')
  })

  it('preserves full-row formatter arguments and precedence over value-only formatting', () => {
    const row = { total: 42 }
    const item = { graphicalItemId: 'bar-0', dataKey: 'total', name: 'Amount invested', value: 42, payload: row, color: 'blue' }
    const formatter = vi.fn(() => <strong>Custom full row</strong>)
    const valueFormatter = vi.fn(() => 'Unused value')
    const { container } = renderTooltip({ active: true, label: 'May', payload: [item], formatter, valueFormatter })
    expect(screen.getByText('May')).toBeTruthy()
    expect(screen.getByText('Custom full row').tagName).toBe('STRONG')
    expect(formatter).toHaveBeenCalledWith(42, 'Amount invested', item, 0, row)
    expect(valueFormatter).not.toHaveBeenCalled()
    expect(screen.queryByText('Amount invested')).toBeNull()
    expect(container.querySelector('[style*="--color-bg"]')).toBeNull()
  })

  it('keeps the existing default number and text rendering without a formatter', () => {
    renderTooltip({ active: true, payload: [
      { graphicalItemId: 'bar-0', name: 'Count', value: 12345 },
      { graphicalItemId: 'bar-1', name: 'Empty month', value: 0 },
      { graphicalItemId: 'bar-2', name: 'Description', value: 'Pending' },
    ] })
    expect(screen.getByText((12345).toLocaleString())).toBeTruthy()
    expect(screen.getByText('0')).toBeTruthy()
    expect(screen.getByText('Pending')).toBeTruthy()
  })

  it('retains inactive and missing-value behavior with value-only formatting', () => {
    const valueFormatter = vi.fn(() => 'Formatted')
    const { rerender } = renderTooltip({ active: false, payload: [{ graphicalItemId: 'bar-0', name: 'Count', value: 1 }], valueFormatter })
    expect(screen.queryByText('Count')).toBeNull()
    rerender(<ChartContainer config={{}}><div><ChartTooltipContent active payload={[{ graphicalItemId: 'bar-0', name: 'Count' }]} valueFormatter={valueFormatter} /></div></ChartContainer>)
    expect(screen.getByText('Count')).toBeTruthy()
    expect(valueFormatter).not.toHaveBeenCalled()
  })
})
