import {
  apiWebSocketUrl,
  jsonRequest,
  requestJson,
  requestOk,
  tickerPathSegment,
} from '@/api/client'
import type { IbStatus } from '@/api/portfolio'

export type AnalysisGreeksSource = 'ib' | 'fallback' | 'solved_iv' | 'missing'
export type AnalysisBetaSource = 'override' | 'computed' | 'fallback'

// USD; gamma is the change in dollar delta for a 1% underlying move.
export type AnalysisExposure = {
  dollar_delta: number
  beta_weighted_delta: number
  gamma: number
  theta: number
  vega: number
}

export type AnalysisLeg = AnalysisExposure & {
  con_id: number | null
  symbol: string
  sec_type: string
  local_symbol: string | null
  right: string | null
  strike: number | null
  expiry: string | null
  currency: string
  quantity: number
  price: number | null
  underlying_price: number | null
  implied_volatility: number | null
  delta: number | null
  greeks_source: AnalysisGreeksSource | null
  fx_rate: number
  flags: string[]
}

export type AnalysisGroup = AnalysisExposure & {
  kind: string
  label: string
  quantity: number
  premium_type: 'credit' | 'debit' | null
  net_premium: number | null
  max_loss: number | null
  assignment_exposure: number
  legs: AnalysisLeg[]
}

export type AnalysisUnderlying = AnalysisExposure & {
  symbol: string
  beta: number
  beta_source: AnalysisBetaSource
  beta_observations: number | null
  underlying_price: number | null
  net_liquidation_percent: number | null
  max_loss: number | null
  max_loss_unlimited: boolean
  assignment_exposure: number
  groups: AnalysisGroup[]
}

export type AnalysisUnsupportedPosition = {
  con_id: number | null
  symbol: string
  sec_type: string
  local_symbol: string | null
  currency: string
  quantity: number
  reason: string
}

export type AnalysisCoverage = {
  positions: number
  fallback_greeks: number
  fallback_beta: number
  unsupported: number
  fx_converted: number
  missing_price: number
}

export type AnalysisSummary = {
  net_liquidation: number | null
  gross_dollar_delta: number
  net_dollar_delta: number
  beta_weighted_delta: number
  beta_weighted_delta_multiple: number | null
  net_gamma: number
  net_theta: number
  net_vega: number
  assignment_exposure: number
  assignment_exposure_percent: number | null
  maintenance_margin: number | null
  margin_utilisation_percent: number | null
  excess_liquidity: number | null
  largest_underlying: string | null
  largest_underlying_percent: number | null
  coverage: AnalysisCoverage
}

export type AnalysisStressCell = {
  spy_move_percent: number
  iv_shock_percent: number
  pnl: number
  pnl_percent: number | null
  // Stressed net liquidation minus calibrated model margin.
  excess_liquidity: number | null
  realistic_path: boolean
}

export type AnalysisMarginEstimate = {
  model_margin: number
  ib_maintenance_margin: number | null
  calibration_factor: number
  excluded_groups: number
  distance_to_margin_call_percent: number | null
  margin_call_beyond_path: boolean
}

// Cells run SPY move first, then IV shock.
export type AnalysisStressGrid = {
  spy_moves_percent: number[]
  iv_shocks_percent: number[]
  cells: AnalysisStressCell[]
  realistic_path: AnalysisStressCell[]
  legs: number
  excluded_legs: number
  margin: AnalysisMarginEstimate
}

// A realised statistic; value is null with a reason when history is too short.
export type AnalysisRealisedValue = {
  value: number | null
  observations: number
  reason: string | null
}

// From the daily NAV history, which includes deposits and withdrawals.
export type AnalysisRealisedStats = {
  currency: string | null
  start_date: string | null
  end_date: string | null
  nav_observations: number
  volatility_20d_percent: AnalysisRealisedValue
  volatility_60d_percent: AnalysisRealisedValue
  // Negative percents from the running peak.
  max_drawdown_percent: AnalysisRealisedValue
  current_drawdown_percent: AnalysisRealisedValue
  beta: AnalysisRealisedValue
}

export type PortfolioAnalysisResponse = {
  status: IbStatus
  account: string | null
  accounts: string[]
  as_of: string
  summary: AnalysisSummary
  underlyings: AnalysisUnderlying[]
  unsupported: AnalysisUnsupportedPosition[]
  stress: AnalysisStressGrid | null
  realised: AnalysisRealisedStats | null
  message: string | null
}

export type RiskSnapshotKind = 'post_close' | 'intraday'

export type AnalysisRiskSnapshot = {
  session_date: string
  kind: RiskSnapshotKind
  captured_at: string
  net_liquidation: number | null
  beta_weighted_delta: number
  beta_weighted_delta_multiple: number | null
  net_gamma: number
  net_theta: number
  net_vega: number
  assignment_exposure: number
  assignment_exposure_percent: number | null
  maintenance_margin: number | null
  margin_utilisation_percent: number | null
  excess_liquidity: number | null
  largest_underlying: string | null
  largest_underlying_percent: number | null
  realistic_down_20_pnl: number | null
  realistic_down_20_pnl_percent: number | null
  model_margin: number | null
  calibration_factor: number | null
  distance_to_margin_call_percent: number | null
  margin_call_beyond_path: boolean
}

export type PortfolioAnalysisHistoryResponse = {
  account: string
  snapshots: AnalysisRiskSnapshot[]
}

export type BetaOverride = {
  ticker: string
  beta: number
  updated_at: string
}

export function portfolioAnalysisWebSocketUrl(account: string | null) {
  const query = account ? `?account=${encodeURIComponent(account)}` : ''
  return apiWebSocketUrl(`/portfolio/analysis/ws${query}`)
}

export async function fetchBetaOverrides(signal?: AbortSignal) {
  return requestJson<BetaOverride[]>(
    '/portfolio/analysis/beta-overrides',
    'Beta overrides',
    { signal },
  )
}

export async function saveBetaOverride(ticker: string, beta: number) {
  return jsonRequest<BetaOverride>(
    `/portfolio/analysis/beta-overrides/${tickerPathSegment(ticker)}`,
    'PUT',
    { beta },
    'Beta override',
  )
}

export async function deleteBetaOverride(ticker: string) {
  await requestOk(
    `/portfolio/analysis/beta-overrides/${tickerPathSegment(ticker)}`,
    'Beta override',
    { method: 'DELETE' },
  )
}

export type RiskLimitKey =
  | 'beta_weighted_delta_multiple'
  | 'margin_utilisation_percent'
  | 'assignment_exposure_percent'
  | 'largest_underlying_percent'
  | 'realistic_path_loss_percent'
  | 'margin_call_distance_percent'

export type RiskLimit = {
  key: RiskLimitKey
  value: number
  updated_at: string
}

export type RiskLimitsResponse = {
  account: string
  limits: RiskLimit[]
}

function riskLimitsPath(account: string) {
  return `/portfolio/analysis/limits/${encodeURIComponent(account)}`
}

export async function fetchRiskLimits(account: string, signal?: AbortSignal) {
  return requestJson<RiskLimitsResponse>(riskLimitsPath(account), 'Risk limits', { signal })
}

export async function saveRiskLimits(account: string, limits: Partial<Record<RiskLimitKey, number>>) {
  return jsonRequest<RiskLimitsResponse>(riskLimitsPath(account), 'PUT', { limits }, 'Risk limits')
}

export async function fetchRiskHistory(account: string, signal?: AbortSignal) {
  return requestJson<PortfolioAnalysisHistoryResponse>(
    `/portfolio/analysis/history?account=${encodeURIComponent(account)}`,
    'Risk history',
    { signal },
  )
}
