import type {
  AnalysisRiskSnapshot,
  RiskLimit,
  RiskLimitKey,
  RiskSnapshotKind,
} from '@/api/portfolioAnalysis'
import { formatMultiple, formatWholeCurrency } from '@/features/portfolio-analysis/lib/format'
import { formatOptionalPercent } from '@/lib/format'

type HistoryMetricKey =
  | 'beta_weighted_delta_multiple'
  | 'margin_utilisation_percent'
  | 'assignment_exposure_percent'
  | 'net_theta'

export type HistoryMetric = {
  key: HistoryMetricKey
  label: string
  format: (value: number | null) => string
  // The saved limit drawn as a reference line, if any.
  limitKey?: RiskLimitKey
}

export const HISTORY_METRICS: HistoryMetric[] = [
  {
    key: 'beta_weighted_delta_multiple',
    label: 'Beta-Wtd Delta / NLV',
    format: formatMultiple,
    limitKey: 'beta_weighted_delta_multiple',
  },
  {
    key: 'margin_utilisation_percent',
    label: 'Margin Used',
    format: formatOptionalPercent,
    limitKey: 'margin_utilisation_percent',
  },
  {
    key: 'assignment_exposure_percent',
    label: 'Assignment / NLV',
    format: formatOptionalPercent,
    limitKey: 'assignment_exposure_percent',
  },
  { key: 'net_theta', label: 'Theta / Day', format: formatWholeCurrency },
]

export type HistoryPoint = {
  // UTC midnight of the session, in milliseconds.
  date: number
  session: string
  // Null for a session without a snapshot, which stays a gap.
  kind: RiskSnapshotKind | null
} & Record<HistoryMetricKey, number | null>

const DAY_MS = 24 * 60 * 60 * 1000

function sessionTime(session: string) {
  return Date.parse(`${session}T00:00:00Z`)
}

function gapPoint(date: number): HistoryPoint {
  return {
    date,
    session: new Date(date).toISOString().slice(0, 10),
    kind: null,
    beta_weighted_delta_multiple: null,
    margin_utilisation_percent: null,
    assignment_exposure_percent: null,
    net_theta: null,
  }
}

/** One point per weekday from the first to the last snapshot; missing sessions are gaps. */
export function historyPoints(snapshots: AnalysisRiskSnapshot[]): HistoryPoint[] {
  const bySession = new Map(snapshots.map((snapshot) => [snapshot.session_date, snapshot]))
  const sessions = [...bySession.keys()].sort()
  if (!sessions.length) {
    return []
  }

  const points: HistoryPoint[] = []
  const last = sessionTime(sessions.at(-1)!)
  for (let date = sessionTime(sessions[0]); date <= last; date += DAY_MS) {
    const weekday = new Date(date).getUTCDay()
    if (weekday === 0 || weekday === 6) {
      continue
    }
    const point = gapPoint(date)
    const snapshot = bySession.get(point.session)
    if (snapshot) {
      point.kind = snapshot.kind
      for (const metric of HISTORY_METRICS) {
        point[metric.key] = snapshot[metric.key]
      }
    }
    points.push(point)
  }
  return points
}

/** Limit lines for a chart; BWD limits apply to the absolute value, so both signs show. */
export function historyLimitLines(
  metric: HistoryMetric,
  limits: RiskLimit[],
  points: HistoryPoint[],
): number[] {
  const limit = limits.find((item) => item.key === metric.limitKey)?.value
  if (limit === undefined) {
    return []
  }
  const hasNegative = points.some((point) => (point[metric.key] ?? 0) < 0)
  return metric.key === 'beta_weighted_delta_multiple' && hasNegative && limit > 0
    ? [limit, -limit]
    : [limit]
}

export function historyDate(value: number | string) {
  return new Intl.DateTimeFormat('en', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(value))
}

export const SNAPSHOT_KIND_LABEL: Record<RiskSnapshotKind, string> = {
  post_close: 'After close',
  intraday: 'Intraday',
}
