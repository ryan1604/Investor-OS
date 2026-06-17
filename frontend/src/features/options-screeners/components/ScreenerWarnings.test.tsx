// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ScreenerWarnings } from '@/features/options-screeners/components/ScreenerWarnings'

afterEach(cleanup)

describe('ScreenerWarnings', () => {
  it('uses informational styling when no tickers failed', () => {
    render(
      <ScreenerWarnings
        errors={[]}
        warnings={[
          {
            ticker: 'AAPL',
            category: 'excluded_contracts',
            message: 'Excluded invalid contracts.',
            count: 3,
          },
        ]}
      />,
    )

    const summary = screen.getByRole('button', { name: /0 failed tickers/ })
    expect(summary.querySelector('.lucide-info')).toBeTruthy()
    expect(summary.parentElement?.className).toContain('border-blue-500/25')
  })

  it('uses error styling when a ticker failed', () => {
    render(
      <ScreenerWarnings
        errors={['AAPL: market data unavailable']}
        warnings={[]}
      />,
    )

    const summary = screen.getByRole('button', { name: /1 failed ticker/ })
    expect(summary.querySelector('.lucide-circle-alert')).toBeTruthy()
    expect(summary.parentElement?.className).toContain('border-red-500/25')
  })
})
