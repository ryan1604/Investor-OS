import type {
  PortfolioAnalysisResponse,
  RiskLimit,
  RiskLimitKey,
} from '@/api/portfolioAnalysis'
import { formatNumber } from '@/lib/format'

export type LimitBand = 'green' | 'amber' | 'red'

// Upper limits are "at most"; lower limits are "at least". The realistic-path
// P&L floor is kept as an upper limit on the loss (P&L >= -limit%).
type LimitDefinition = {
  key: RiskLimitKey
  label: string
  direction: 'upper' | 'lower'
  unit: 'x' | '%'
  // Shown next to the editor field.
  hint: string
  suggested: number
}

export const LIMIT_DEFINITIONS: LimitDefinition[] = [
  {
    key: 'beta_weighted_delta_multiple',
    label: 'Beta-Wtd Delta / NLV',
    direction: 'upper',
    unit: 'x',
    hint: 'at most, x NLV',
    suggested: 1,
  },
  {
    key: 'margin_utilisation_percent',
    label: 'Margin Used',
    direction: 'upper',
    unit: '%',
    hint: 'at most, %',
    suggested: 30,
  },
  {
    key: 'assignment_exposure_percent',
    label: 'Assignment / NLV',
    direction: 'upper',
    unit: '%',
    hint: 'at most, % of NLV',
    suggested: 50,
  },
  {
    key: 'largest_underlying_percent',
    label: 'Largest Underlying',
    direction: 'upper',
    unit: '%',
    hint: 'at most, % of NLV',
    suggested: 15,
  },
  {
    key: 'realistic_path_loss_percent',
    label: 'Realistic -20% Loss',
    direction: 'upper',
    unit: '%',
    hint: 'loss at most, % of NLV',
    suggested: 25,
  },
  {
    key: 'margin_call_distance_percent',
    label: 'Margin Call Distance',
    direction: 'lower',
    unit: '%',
    hint: 'at least, % SPY drop',
    suggested: 25,
  },
]

// Amber starts at 80% of an upper limit, or within 20% above a lower limit.
const UPPER_AMBER_RATIO = 0.8
const LOWER_AMBER_RATIO = 1.2

export const LIMIT_BAND_TEXT_CLASS: Record<LimitBand, string> = {
  green: 'text-emerald-500',
  amber: 'text-amber-500',
  red: 'text-red-500',
}

export function limitBand(
  direction: LimitDefinition['direction'],
  value: number | null,
  limit: number,
): LimitBand | null {
  if (value === null || Number.isNaN(value)) {
    return null
  }
  if (direction === 'upper') {
    if (value > limit) {
      return 'red'
    }
    return value >= limit * UPPER_AMBER_RATIO ? 'amber' : 'green'
  }
  if (value < limit) {
    return 'red'
  }
  return value < limit * LOWER_AMBER_RATIO ? 'amber' : 'green'
}

/** The metric a limit applies to; Infinity means a margin call is beyond the modelled path. */
export function limitMetric(
  key: RiskLimitKey,
  analysis: PortfolioAnalysisResponse,
): number | null {
  const { summary, stress } = analysis
  switch (key) {
    case 'beta_weighted_delta_multiple':
      return summary.beta_weighted_delta_multiple === null
        ? null
        : Math.abs(summary.beta_weighted_delta_multiple)
    case 'margin_utilisation_percent':
      return summary.margin_utilisation_percent
    case 'assignment_exposure_percent':
      return summary.assignment_exposure_percent
    case 'largest_underlying_percent':
      return summary.largest_underlying_percent
    case 'realistic_path_loss_percent': {
      const pnl = stress?.realistic_path.find((cell) => cell.spy_move_percent === -20)?.pnl_percent
      return pnl === undefined || pnl === null ? null : Math.max(0, -pnl)
    }
    case 'margin_call_distance_percent':
      if (stress?.margin.margin_call_beyond_path) {
        return Number.POSITIVE_INFINITY
      }
      return stress?.margin.distance_to_margin_call_percent ?? null
  }
}

export function formatLimitValue(definition: LimitDefinition, value: number | null) {
  if (value === null) {
    return '-'
  }
  if (value === Number.POSITIVE_INFINITY) {
    return '> 30%'
  }
  const digits = definition.unit === 'x' ? 2 : 1
  const number = formatNumber(value, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
  return `${number}${definition.unit}`
}

export function limitRule(definition: LimitDefinition, limit: number) {
  const value = formatLimitValue(definition, limit)
  if (definition.key === 'realistic_path_loss_percent') {
    return `P&L >= -${value}`
  }
  return `${definition.direction === 'upper' ? '<=' : '>='} ${value}`
}

export type LimitStatus = {
  definition: LimitDefinition
  limit: number
  value: number | null
  band: LimitBand | null
}

/** Status for each saved limit; unsaved limits have no status. */
export function limitStatuses(
  limits: RiskLimit[],
  analysis: PortfolioAnalysisResponse | null,
): LimitStatus[] {
  if (!analysis) {
    return []
  }
  return LIMIT_DEFINITIONS.flatMap((definition) => {
    const saved = limits.find((limit) => limit.key === definition.key)
    if (!saved) {
      return []
    }
    const value = limitMetric(definition.key, analysis)
    return [
      {
        definition,
        limit: saved.value,
        value,
        band: limitBand(definition.direction, value, saved.value),
      },
    ]
  })
}

export type LimitBands = Partial<Record<RiskLimitKey, LimitBand>>

export function limitBandsByKey(statuses: LimitStatus[]): LimitBands {
  return Object.fromEntries(
    statuses.flatMap((status) => (status.band ? [[status.definition.key, status.band]] : [])),
  ) as LimitBands
}

/** Band text colour for a limited metric, or the fallback when it has no band. */
export function limitTextClass(bands: LimitBands, key: RiskLimitKey, fallback?: string) {
  const band = bands[key]
  return band ? LIMIT_BAND_TEXT_CLASS[band] : fallback
}
