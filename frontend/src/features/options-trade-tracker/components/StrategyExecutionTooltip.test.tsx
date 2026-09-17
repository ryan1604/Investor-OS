// @vitest-environment jsdom

import { StrictMode, type ComponentProps } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ChartContainer } from '@/components/ui/chart'
import { StrategyExecutionTooltip } from './StrategyExecutionTooltip'

type Props = ComponentProps<typeof StrategyExecutionTooltip>
const data = [
  { strategy: 'CC', strategyKey: 'strategy_0', count: 9 },
  { strategy: 'CUSTOM / RATIO SPREAD', strategyKey: 'strategy_1', count: 12345 },
]
function payload(index: number, slices = data): Props['payload'] {
  const slice = slices[index]
  return [{ graphicalItemId: 'pie', dataKey: 'count', name: slice.strategy, value: slice.count, payload: { ...slice, fill: index === 0 ? 'blue' : 'green' } }]
}
function tooltip(props: Partial<Props> = {}) {
  return (
    <StrictMode>
      <ChartContainer config={{ strategy_0: { label: 'CC' }, strategy_1: { label: 'CUSTOM / RATIO SPREAD' } }}>
        <div><StrategyExecutionTooltip data={data} {...props} /></div>
      </ChartContainer>
    </StrictMode>
  )
}

afterEach(cleanup)

describe('StrategyExecutionTooltip', () => {
  it('starts empty and retains the last content node while inactive', () => {
    const { container, rerender } = render(tooltip({ active: false, payload: [] }))
    expect(screen.queryByText('CC')).toBeNull()
    rerender(tooltip({ active: true, payload: payload(0) }))
    const name = screen.getByText('CC')
    expect(screen.getByText('9')).toBeTruthy()
    rerender(tooltip({ active: false, payload: [] }))
    expect(screen.getByText('CC')).toBe(name)
    expect(screen.getByText('9')).toBeTruthy()
    expect(container.querySelector<HTMLElement>('[style*="--color-bg"]')?.style.getPropertyValue('--color-bg')).toBe('blue')
  })

  it('replaces names, counts, and indicators immediately after a gap or direct transition', () => {
    const { container, rerender } = render(tooltip({ active: true, payload: payload(0) }))
    rerender(tooltip({ active: false, payload: [] }))
    rerender(tooltip({ active: true, payload: payload(1) }))
    expect(screen.queryByText('CC')).toBeNull()
    expect(screen.getByText('CUSTOM / RATIO SPREAD')).toBeTruthy()
    expect(screen.getByText('12,345')).toBeTruthy()
    expect(container.querySelector<HTMLElement>('[style*="--color-bg"]')?.style.getPropertyValue('--color-bg')).toBe('green')
    rerender(tooltip({ active: true, payload: payload(0) }))
    expect(screen.getByText('CC')).toBeTruthy()
    expect(screen.queryByText('12,345')).toBeNull()
  })

  it('clears retained content when the data changes while inactive', () => {
    const { rerender } = render(tooltip({ active: true, payload: payload(0) }))
    rerender(tooltip({ active: false, payload: [], data: [...data] }))
    expect(screen.queryByText('CC')).toBeNull()
    // Returning to the previous data reference must not resurrect a hover session.
    rerender(tooltip({ active: false, payload: [] }))
    expect(screen.queryByText('CC')).toBeNull()
  })

  it('rejects a stale active payload until the changed count reaches the tooltip', () => {
    const { rerender } = render(tooltip({ active: true, payload: payload(0) }))
    const updated = [{ ...data[0], count: 10 }, data[1]]
    rerender(tooltip({ active: true, payload: payload(0), data: updated }))
    expect(screen.queryByText('9')).toBeNull()
    expect(screen.queryByText('CC')).toBeNull()
    rerender(tooltip({ active: true, payload: payload(0, updated), data: updated }))
    expect(screen.getByText('CC')).toBeTruthy()
    expect(screen.getByText('10')).toBeTruthy()
  })

  it('rejects removed strategies even if another strategy reuses their internal key', () => {
    const { rerender } = render(tooltip({ active: true, payload: payload(0) }))
    rerender(tooltip({ active: true, payload: payload(0), data: [{ ...data[0], strategy: 'NEW STRATEGY' }] }))
    expect(screen.queryByText('CC')).toBeNull()
    expect(screen.queryByText('9')).toBeNull()
    rerender(tooltip({ active: false, payload: [], data: [] }))
    expect(screen.queryByText('CC')).toBeNull()
  })

  it.each([
    { name: 'empty', payload: [] },
    { name: 'missing value', payload: [{ ...payload(0)![0], value: undefined }] },
    { name: 'nonfinite value', payload: [{ ...payload(0)![0], value: NaN }] },
  ])('clears a $name active payload without falling back to an old value', ({ payload: invalid }) => {
    const { rerender } = render(tooltip({ active: true, payload: payload(0) }))
    rerender(tooltip({ active: true, payload: invalid }))
    expect(screen.queryByText('CC')).toBeNull()
    rerender(tooltip({ active: false, payload: [] }))
    expect(screen.queryByText('CC')).toBeNull()
  })

  it('starts a fresh session after unmounting', () => {
    const { unmount } = render(tooltip({ active: true, payload: payload(0) }))
    unmount()
    render(tooltip({ active: false, payload: [] }))
    expect(screen.queryByText('CC')).toBeNull()
  })
})
