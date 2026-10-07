// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { RealisedStats } from '@/features/portfolio-analysis/components/RealisedStats'
import { realisedStats } from '@/features/portfolio-analysis/testFixtures'

afterEach(cleanup)

describe('RealisedStats', () => {
  it('shows the realised figures, the NAV window and the cash-flow caveat', () => {
    render(<RealisedStats realised={realisedStats()} />)

    expect(screen.getByText('18.40%')).toBeTruthy()
    expect(screen.getByText('22.10%')).toBeTruthy()
    expect(screen.getByText('-12.50%')).toBeTruthy()
    expect(screen.getByText('-3.20%')).toBeTruthy()
    expect(screen.getByText(/Jun 2 2025 - Sep 25 2026 · 340 daily NAVs \(USD\)/)).toBeTruthy()
    expect(screen.getByRole('img', { name: /Deposits and withdrawals/ })).toBeTruthy()
  })

  it('explains a statistic without enough history', () => {
    render(
      <RealisedStats
        realised={realisedStats({
          volatility_60d_percent: {
            value: null,
            observations: 29,
            reason: 'Needs 60 daily NAV returns; 29 available.',
          },
          beta: { value: 1.234, observations: 252, reason: null },
        })}
      />,
    )

    expect(screen.getByRole('img', { name: 'Needs 60 daily NAV returns; 29 available.' })).toBeTruthy()
    expect(screen.getByText('1.23')).toBeTruthy()
    expect(screen.getByText('252 days vs SPY')).toBeTruthy()
    expect(screen.getAllByText('annualised')).toHaveLength(1)
  })

  it('says when there is no NAV history', () => {
    render(
      <RealisedStats
        realised={realisedStats({ start_date: null, end_date: null, nav_observations: 0 })}
      />,
    )

    expect(screen.getByText('No daily NAV history yet.')).toBeTruthy()
  })
})
