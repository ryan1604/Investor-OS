// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { RiskHistory } from '@/features/portfolio-analysis/components/RiskHistory'
import { riskHistory } from '@/features/portfolio-analysis/testFixtures'

afterEach(cleanup)

function renderHistory(limits = [{ key: 'beta_weighted_delta_multiple' as const, value: 1, updated_at: '' }]) {
  return render(
    <RiskHistory snapshots={riskHistory()} limits={limits} isLoaded error={null} />,
  )
}

describe('RiskHistory', () => {
  it('charts each metric with gaps and marked intraday points', () => {
    renderHistory()

    for (const label of ['Beta-Wtd Delta / NLV', 'Margin Used', 'Assignment / NLV', 'Theta / Day']) {
      expect(screen.getByLabelText(`${label} history`)).toBeTruthy()
    }
    const bwd = screen.getByLabelText('Beta-Wtd Delta / NLV history')
    expect(bwd.querySelectorAll('circle[data-kind="post_close"]')).toHaveLength(3)
    expect(bwd.querySelectorAll('circle[data-kind="intraday"]')).toHaveLength(1)
    // The missing Wednesday splits the line into two segments.
    const line = bwd.querySelector('.recharts-line-curve')!.getAttribute('d')!
    expect(line.match(/M/g)).toHaveLength(2)

    // Friday's intraday margin is missing, so only the three closes have points.
    const margin = screen.getByLabelText('Margin Used history')
    expect(margin.querySelectorAll('circle[data-kind]')).toHaveLength(3)
  })

  it('draws saved limits as reference lines', () => {
    renderHistory()

    const bwd = screen.getByLabelText('Beta-Wtd Delta / NLV history')
    // BWD dips below zero, so the absolute limit shows at +1x and -1x.
    expect(bwd.querySelectorAll('.recharts-reference-line')).toHaveLength(2)
    expect(bwd.textContent).toContain('Limit 1.00x')
    const margin = screen.getByLabelText('Margin Used history')
    expect(margin.querySelectorAll('.recharts-reference-line')).toHaveLength(0)
  })

  it('shows an empty state and errors', () => {
    render(<RiskHistory snapshots={[]} limits={[]} isLoaded error="Risk history request failed" />)

    expect(screen.getByText('No risk history yet.')).toBeTruthy()
    expect(screen.getByText('Risk history request failed')).toBeTruthy()
  })
})
