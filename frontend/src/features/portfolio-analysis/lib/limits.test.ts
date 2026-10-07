import { describe, expect, it } from 'vitest'

import type { RiskLimit, RiskLimitKey } from '@/api/portfolioAnalysis'
import {
  formatLimitValue,
  LIMIT_DEFINITIONS,
  limitBand,
  limitMetric,
  limitRule,
  limitStatuses,
} from '@/features/portfolio-analysis/lib/limits'
import { analysisResponse, stressGrid } from '@/features/portfolio-analysis/testFixtures'

function definition(key: RiskLimitKey) {
  return LIMIT_DEFINITIONS.find((item) => item.key === key)!
}

function saved(key: RiskLimitKey, value: number): RiskLimit {
  return { key, value, updated_at: '2026-09-26T00:00:00Z' }
}

describe('limitBand', () => {
  it('bands an upper limit with amber from 80% of the limit', () => {
    expect(limitBand('upper', 23.9, 30)).toBe('green')
    expect(limitBand('upper', 24, 30)).toBe('amber')
    expect(limitBand('upper', 30, 30)).toBe('amber')
    expect(limitBand('upper', 30.1, 30)).toBe('red')
  })

  it('bands a lower limit with amber up to 20% above the limit', () => {
    expect(limitBand('lower', 24.9, 25)).toBe('red')
    expect(limitBand('lower', 25, 25)).toBe('amber')
    expect(limitBand('lower', 29.9, 25)).toBe('amber')
    expect(limitBand('lower', 30, 25)).toBe('green')
    expect(limitBand('lower', Number.POSITIVE_INFINITY, 25)).toBe('green')
  })

  it('has no band without a value', () => {
    expect(limitBand('upper', null, 30)).toBeNull()
    expect(limitBand('lower', null, 25)).toBeNull()
  })
})

describe('limitMetric', () => {
  it('uses the absolute beta-weighted delta multiple', () => {
    const base = analysisResponse()
    const analysis = {
      ...base,
      summary: { ...base.summary, beta_weighted_delta_multiple: -1.3 },
    }
    expect(limitMetric('beta_weighted_delta_multiple', analysis)).toBe(1.3)
  })

  it('reads the realistic -20% loss as a positive percent of NLV', () => {
    // Fixture: SPY -20% with IV +80% loses $28,000, or 28% of NLV.
    expect(limitMetric('realistic_path_loss_percent', analysisResponse())).toBe(28)

    const gain = stressGrid()
    gain.realistic_path = gain.realistic_path.map((cell) => ({ ...cell, pnl_percent: 4 }))
    expect(limitMetric('realistic_path_loss_percent', { ...analysisResponse(), stress: gain })).toBe(0)
  })

  it('treats a margin call beyond the path as infinitely far', () => {
    const beyond = stressGrid({
      margin: {
        ...stressGrid().margin,
        distance_to_margin_call_percent: null,
        margin_call_beyond_path: true,
      },
    })
    const analysis = { ...analysisResponse(), stress: beyond }
    expect(limitMetric('margin_call_distance_percent', analysis)).toBe(Number.POSITIVE_INFINITY)
    expect(formatLimitValue(definition('margin_call_distance_percent'), Infinity)).toBe('> 30%')
  })

  it('has no stress metrics without a grid', () => {
    const analysis = { ...analysisResponse(), stress: null }
    expect(limitMetric('realistic_path_loss_percent', analysis)).toBeNull()
    expect(limitMetric('margin_call_distance_percent', analysis)).toBeNull()
  })
})

describe('limitStatuses', () => {
  it('reports saved limits only, banded against the live analysis', () => {
    const statuses = limitStatuses(
      [
        saved('realistic_path_loss_percent', 30),
        saved('margin_call_distance_percent', 20),
      ],
      analysisResponse(),
    )

    expect(
      statuses.map((status) => [status.definition.key, status.value, status.band]),
    ).toEqual([
      // 28% loss against a 30% floor is inside the 80% amber zone.
      ['realistic_path_loss_percent', 28, 'amber'],
      // 21.4% distance against 20% is within 20% above the limit.
      ['margin_call_distance_percent', 21.4, 'amber'],
    ])
    expect(limitRule(statuses[0].definition, 30)).toBe('P&L >= -30.0%')
    expect(limitRule(statuses[1].definition, 20)).toBe('>= 20.0%')
  })

  it('reports nothing without saved limits or analysis', () => {
    expect(limitStatuses([], analysisResponse())).toEqual([])
    expect(limitStatuses([saved('margin_utilisation_percent', 30)], null)).toEqual([])
  })
})
