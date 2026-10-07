import {
  apiWebSocketUrl,
  requestJson,
  tickerPathSegment,
} from '@/api/client'

export type OptionDailyCandle = {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number | null
}

export type BollingerBandPoint = {
  date: string
  upper: number | null
  middle: number | null
  lower: number | null
}

export type RsiPoint = {
  date: string
  value: number | null
}

export type OptionExpiration = {
  date: string
  days_to_expiration: number | null
}

export type OptionQuote = {
  local_symbol: string | null
  delta: number | null
  bid: number | null
  bid_size: number | null
  ask: number | null
  ask_size: number | null
  mid: number | null
  last: number | null
  close: number | null
  model_price: number | null
  change_percent: number | null
  volume: number | null
  open_interest: number | null
  gamma: number | null
  theta: number | null
  implied_volatility_percent: number | null
  breakeven: number | null
}

export type OptionChainRow = {
  strike: number
  call: OptionQuote | null
  put: OptionQuote | null
}

export type OptionsAnalysisResponse = {
  ticker: string
  underlying_price: number | null
  candles: OptionDailyCandle[]
  bollinger_bands: BollingerBandPoint[]
  rsi: RsiPoint[]
  message: string | null
}

export type OptionExpirationsResponse = {
  ticker: string
  expirations: OptionExpiration[]
  selected_expiration: string | null
  message: string | null
}

export type OptionChainResponse = {
  ticker: string
  expiration: string
  underlying_price: number | null
  rows: OptionChainRow[]
  message: string | null
  warning?: string | null
}

export type OptionChainLiveMessage = {
  type: 'snapshot' | 'update'
  ticker: string
  expiration: string
  rows?: OptionChainRow[]
  row?: OptionChainRow
  message?: string | null
  warning?: string | null
}

export type OptionsChartLiveMessage = {
  type: 'update'
  ticker: string
  candle: OptionDailyCandle
  bollinger_band: BollingerBandPoint
  rsi: RsiPoint
}

export async function fetchOptionsAnalysis(ticker: string, signal?: AbortSignal) {
  return requestJson<OptionsAnalysisResponse>(
    `/options/${tickerPathSegment(ticker)}/analysis`,
    'Options analysis',
    { signal },
  )
}

export async function fetchOptionExpirations(ticker: string, signal?: AbortSignal) {
  return requestJson<OptionExpirationsResponse>(
    `/options/${tickerPathSegment(ticker)}/expirations`,
    'Option expirations',
    { signal },
  )
}

export function getOptionChainWsUrl(ticker: string, expiration: string) {
  const params = new URLSearchParams({ expiration })

  return apiWebSocketUrl(
    `/options/${tickerPathSegment(ticker)}/chain/ws?${params}`,
  )
}

export function getOptionsChartWsUrl(ticker: string) {
  return apiWebSocketUrl(`/options/${tickerPathSegment(ticker)}/chart/ws`)
}
