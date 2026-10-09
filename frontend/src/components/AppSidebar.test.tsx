// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppSidebar } from '@/components/AppSidebar'

afterEach(cleanup)

describe('AppSidebar', () => {
  it('preserves the navigation order, labels, and icons', () => {
    render(<AppSidebar activePage="portfolio" onPageChange={vi.fn()} />)
    const buttons = within(screen.getByRole('navigation', { name: 'Primary' }))
      .getAllByRole('button')

    expect(buttons.map((button) => button.textContent)).toEqual([
      'Portfolio', 'Portfolio Analysis', 'Options', 'Orders',
      'CSP Screener', 'CC Screener', 'CS Screener', 'Options Trade Tracker',
      'Day Trading Tracker', 'Stock Analysis', 'Earnings Watch', 'Rank Stocks',
    ])
    expect(buttons.map((button) => button.querySelector('svg')?.getAttribute('class')))
      .toEqual([
        'lucide lucide-briefcase-business', 'lucide lucide-gauge',
        'lucide lucide-chart-candlestick', 'lucide lucide-list-checks',
        'lucide lucide-radar', 'lucide lucide-radar', 'lucide lucide-radar',
        'lucide lucide-clipboard-list', 'lucide lucide-calendar-days',
        'lucide lucide-chart-no-axes-combined', 'lucide lucide-calendar-clock',
        'lucide lucide-list-ordered',
      ])
  })

  it('marks only the active page and sends its registry id on navigation', () => {
    const onPageChange = vi.fn()
    render(<AppSidebar activePage="orders" onPageChange={onPageChange} />)
    const navigation = screen.getByRole('navigation', { name: 'Primary' })
    expect(navigation.querySelectorAll('[aria-current="page"]')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Orders' }).getAttribute('aria-current'))
      .toBe('page')

    fireEvent.click(screen.getByRole('button', { name: 'Portfolio Analysis' }))
    expect(onPageChange).toHaveBeenCalledExactlyOnceWith('portfolio-analysis')
  })
})
