import { jsonRequest, requestJson, tickerPathSegment } from '@/api/client'

export type EarningsWatchRowStatus = 'upcoming' | 'last_known' | 'no_date'

export type EarningsWatchRefreshStatus =
  | 'never_attempted'
  | 'refreshing'
  | 'succeeded'
  | 'failed'
  | 'cooldown'

export type EarningsWatchRow = {
  ticker: string
  reviewed: boolean
  earnings_date: string | null
  status: EarningsWatchRowStatus
  created_at: string
  updated_at: string
}

export type EarningsWatchRefreshState = {
  state: EarningsWatchRefreshStatus
  last_attempt_at: string | null
  last_success_at: string | null
  last_success_date: string | null
  error_category: string | null
  next_eligible_retry_at: string | null
}

export type EarningsWatchResponse = {
  rows: EarningsWatchRow[]
  refresh: EarningsWatchRefreshState
}

export type EarningsWatchStateResponse = {
  rows: EarningsWatchRow[]
}

export type EarningsWatchAddTickersResponse = EarningsWatchStateResponse & {
  added: string[]
  existing: string[]
  rejected: string[]
}

export async function fetchEarningsWatch(signal?: AbortSignal) {
  return requestJson<EarningsWatchResponse>('/earnings-watch', 'Earnings Watch', {
    signal,
  })
}

export async function addEarningsWatchTickers(
  tickers: string,
  signal?: AbortSignal,
) {
  return jsonRequest<EarningsWatchAddTickersResponse>(
    '/earnings-watch/tickers',
    'POST',
    { tickers },
    'Earnings Watch',
    signal,
  )
}

export async function removeEarningsWatchTicker(
  ticker: string,
  signal?: AbortSignal,
) {
  return requestJson<EarningsWatchRow>(
    `/earnings-watch/tickers/${tickerPathSegment(ticker)}`,
    'Earnings Watch',
    {
      method: 'DELETE',
      signal,
    },
  )
}

export async function setEarningsWatchReviewed(
  ticker: string,
  reviewed: boolean,
  signal?: AbortSignal,
) {
  return jsonRequest<EarningsWatchRow>(
    `/earnings-watch/tickers/${tickerPathSegment(ticker)}/reviewed`,
    'PUT',
    { reviewed },
    'Earnings Watch',
    signal,
  )
}

export async function clearEarningsWatchReviews(signal?: AbortSignal) {
  return requestJson<EarningsWatchStateResponse>(
    '/earnings-watch/reviews/clear',
    'Earnings Watch',
    {
      method: 'POST',
      signal,
    },
  )
}
