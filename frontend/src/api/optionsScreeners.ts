import {
  apiWebSocketUrl,
  jsonRequest,
  requestJson,
} from '@/api/client'
import type {
  OptionContractIdentity,
  ScreenerCandidate,
} from '@/features/options-screeners/lib/screenerResults'

export type OptionsScreenerTickerList = 'csp_cc' | 'cs'
export type OptionsScreener = 'csp' | 'cc' | 'cs'
export type CreditSpreadStrategy =
  | 'put_credit_spread'
  | 'call_credit_spread'
export type CreditSpreadWidth = 1 | 2 | 2.5 | 5 | 10

export type OptionsScreenerFilters = {
  version: number
  minimum_dte: number
  maximum_dte: number
  minimum_absolute_delta: number
  maximum_absolute_delta: number
  minimum_annualized_return: number
}

export type CreditSpreadScreenerFilters = OptionsScreenerFilters & {
  strategy_types: CreditSpreadStrategy[]
  spread_widths: CreditSpreadWidth[]
}

export type OptionsScreenerSettingsResponse = {
  ticker_lists: Record<OptionsScreenerTickerList, string[]>
  filters: {
    csp: OptionsScreenerFilters
    cc: OptionsScreenerFilters
    cs: CreditSpreadScreenerFilters
  }
}

export type OptionsScreenerTickerListResponse = {
  list_name: OptionsScreenerTickerList
  tickers: string[]
}

export type OptionsScreenerJobStatus =
  | 'active'
  | 'completed'
  | 'cancelled'
  | 'failed'

export type OptionsScreenerScanJob = {
  id: string
  screener: OptionsScreener
  status: OptionsScreenerJobStatus
  tickers: string[]
  filters: OptionsScreenerFilters | CreditSpreadScreenerFilters
  total_tickers: number
  completed_tickers: number
  progress_message: string
  successful_tickers: number
  no_match_tickers: number
  failed_tickers: number
  total_match_count: number
  excluded_contracts: number
  candidates: ScreenerCandidate[]
  errors: string[]
  warnings: OptionsScreenerTickerWarning[]
  started_at: string
  finished_at: string | null
  successful_completion_at: string | null
}

export type OptionsScreenerCompletedSnapshot = {
  screener: OptionsScreener
  job_id: string
  total_match_count: number
  excluded_contracts: number
  candidates: ScreenerCandidate[]
  errors: string[]
  warnings: OptionsScreenerTickerWarning[]
  completed_at: string
}

export type OptionsScreenerTickerWarning = {
  ticker: string
  category: 'excluded_contracts' | 'line_limit' | 'no_matches'
  message: string
  count: number
}

export type OptionsScreenerScanState = {
  active_job: OptionsScreenerScanJob | null
  latest_jobs: Record<OptionsScreener, OptionsScreenerScanJob | null>
  completed_snapshots: Record<
    OptionsScreener,
    OptionsScreenerCompletedSnapshot | null
  >
}

export type OptionsScreenerScanEvent = {
  type: 'job_started' | 'job_updated' | 'job_finished'
  job: OptionsScreenerScanJob
}

export type OptionsScreenerQuoteRefreshRequest = {
  ticker: string
  expiration: string
  strike: number
  right: 'CALL' | 'PUT'
  contract: OptionContractIdentity
}

export type OptionsScreenerQuoteRefreshResponse =
  OptionsScreenerQuoteRefreshRequest & {
    bid: number
    ask: number
    midpoint: number
    delta: number | null
    refreshed_at: string
  }

export type OptionsScreenerSpreadQuoteRefreshRequest = {
  strategy: CreditSpreadStrategy
  ticker: string
  expiration: string
  short_strike: number
  long_strike: number
  short_contract: OptionContractIdentity
  long_contract: OptionContractIdentity
}

export type OptionsScreenerSpreadQuoteRefreshResponse =
  OptionsScreenerSpreadQuoteRefreshRequest & {
    right: 'CALL' | 'PUT'
    short_bid: number
    short_ask: number
    short_midpoint: number
    long_bid: number
    long_ask: number
    long_midpoint: number
    short_delta: number | null
    net_bid: number
    net_ask: number
    net_midpoint: number
    maximum_loss: number
    refreshed_at: string
  }

const settingsPath = '/options-screeners/settings'
const screenersPath = '/options-screeners'

export async function fetchOptionsScreenerSettings(signal?: AbortSignal) {
  return requestJson<OptionsScreenerSettingsResponse>(
    settingsPath,
    'Options screener settings',
    { signal },
  )
}

export async function replaceOptionsScreenerTickerList(
  listName: OptionsScreenerTickerList,
  tickers: string[],
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsScreenerTickerListResponse>(
    `${settingsPath}/ticker-lists/${listName}`,
    'PUT',
    { tickers },
    'Options screener settings',
    signal,
  )
}

export async function saveOptionsScreenerFilters(
  screener: 'csp' | 'cc',
  filters: OptionsScreenerFilters,
  signal?: AbortSignal,
): Promise<OptionsScreenerFilters>
export async function saveOptionsScreenerFilters(
  screener: 'cs',
  filters: CreditSpreadScreenerFilters,
  signal?: AbortSignal,
): Promise<CreditSpreadScreenerFilters>
export async function saveOptionsScreenerFilters(
  screener: OptionsScreener,
  filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsScreenerFilters | CreditSpreadScreenerFilters>(
    `${settingsPath}/filters/${screener}`,
    'PUT',
    filters,
    'Options screener settings',
    signal,
  )
}

export async function fetchOptionsScreenerScanState(signal?: AbortSignal) {
  return requestJson<OptionsScreenerScanState>(
    `${screenersPath}/state`,
    'Options screener settings',
    { signal },
  )
}

export async function startOptionsScreenerScan(
  screener: OptionsScreener,
  signal?: AbortSignal,
) {
  return requestJson<OptionsScreenerScanJob>(
    `${screenersPath}/scans/${screener}`,
    'Options screener settings',
    { method: 'POST', signal },
  )
}

export async function cancelOptionsScreenerScan(
  jobId: string,
  signal?: AbortSignal,
) {
  return requestJson<OptionsScreenerScanJob>(
    `${screenersPath}/scans/${encodeURIComponent(jobId)}/cancel`,
    'Options screener settings',
    { method: 'POST', signal },
  )
}

export async function refreshOptionsScreenerQuote(
  quoteRequest: OptionsScreenerQuoteRefreshRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsScreenerQuoteRefreshResponse>(
    `${screenersPath}/quotes/refresh`,
    'POST',
    quoteRequest,
    'Options screener settings',
    signal,
  )
}

export async function refreshOptionsScreenerSpreadQuote(
  quoteRequest: OptionsScreenerSpreadQuoteRefreshRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsScreenerSpreadQuoteRefreshResponse>(
    `${screenersPath}/quotes/refresh-spread`,
    'POST',
    quoteRequest,
    'Options screener settings',
    signal,
  )
}

export function getOptionsScreenerScansWsUrl() {
  return apiWebSocketUrl(`${screenersPath}/scans/ws`)
}
