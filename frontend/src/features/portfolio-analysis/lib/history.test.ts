import { describe, expect, it } from 'vitest'

import type { RiskLimit } from '@/api/portfolioAnalysis'
import {
  HISTORY_METRICS,
  historyLimitLines,
  historyPoints,
} from '@/features/portfolio-analysis/lib/history'
import { riskHistory, riskSnapshot } from '@/features/portfolio-analysis/testFixtures'

function metric(key: string) {
  return HISTORY_METRICS.find((item) => item.key === key)!
}

function limit(key: RiskLimit['key'], value: number): RiskLimit {
  return { key, value, updated_at: '2026-09-26T00:00:00Z' }
}

describe('historyPoints', () => {
  it('keeps a weekday without a snapshot as a gap', () => {
    const points = historyPoints(riskHistory())

    expect(points.map((point) => [point.session, point.kind])).toEqual([
      ['2026-09-21', 'post_close'],
      ['2026-09-22', 'post_close'],
      ['2026-09-23', null],
      ['2026-09-24', 'post_close'],
      ['2026-09-25', 'intraday'],
    ])
    expect(points[2].beta_weighted_delta_multiple).toBeNull()
    expect(points[2].net_theta).toBeNull()
    expect(points[4].margin_utilisation_percent).toBeNull()
    expect(points[4].beta_weighted_delta_multiple).toBe(0.6)
    expect(points[0].date).toBe(Date.UTC(2026, 8, 21))
  })

  it('skips weekends and sorts sessions', () => {
    const points = historyPoints([riskSnapshot('2026-09-28'), riskSnapshot('2026-09-25')])

    expect(points.map((point) => point.session)).toEqual(['2026-09-25', '2026-09-28'])
    expect(historyPoints([])).toEqual([])
  })
})

describe('historyLimitLines', () => {
  const points = historyPoints(riskHistory())

  it('draws both signs for the absolute beta-weighted delta limit when needed', () => {
    const limits = [limit('beta_weighted_delta_multiple', 1)]
    const bwd = metric('beta_weighted_delta_multiple')

    expect(historyLimitLines(bwd, limits, points)).toEqual([1, -1])
    const positive = historyPoints([riskSnapshot('2026-09-21')])
    expect(historyLimitLines(bwd, limits, positive)).toEqual([1])
  })

  it('draws saved limits only, and never for theta', () => {
    const limits = [limit('margin_utilisation_percent', 30)]

    expect(historyLimitLines(metric('margin_utilisation_percent'), limits, points)).toEqual([30])
    expect(historyLimitLines(metric('assignment_exposure_percent'), limits, points)).toEqual([])
    expect(historyLimitLines(metric('net_theta'), limits, points)).toEqual([])
  })
})
