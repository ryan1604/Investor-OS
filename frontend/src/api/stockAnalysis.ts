import { jsonRequest, requestJson, tickerPathSegment } from '@/api/client'

export type StockAnalysisJsonValue =
  | string
  | number
  | boolean
  | null
  | StockAnalysisJsonValue[]
  | { [key: string]: StockAnalysisJsonValue }

export type StockAnalysisScenarioPayload = Record<string, StockAnalysisJsonValue>

export type StockAnalysisPayload = {
  firstForecastYear?: number | null
  bull: StockAnalysisScenarioPayload
  base: StockAnalysisScenarioPayload
  bear: StockAnalysisScenarioPayload
}

export type StockAnalysisModel = {
  ticker: string
  version: number
  current_price: number | null
  payload: StockAnalysisPayload
  updated_at: string | null
}

export type StockAnalysisModelRequest = {
  version?: number
  payload: StockAnalysisPayload
}

export type StockAnalysisCurrentPriceResponse = {
  ticker: string
  current_price: number
}

export type StockAnalysisPriceRefreshStatus =
  | 'refreshed'
  | 'stale'
  | 'missing'
  | 'failed'

export type StockAnalysisPriceRefreshResult = {
  ticker: string
  status: StockAnalysisPriceRefreshStatus
  current_price: number | null
  message: string | null
}

export type StockAnalysisPriceRefreshResponse = {
  results: StockAnalysisPriceRefreshResult[]
}

export async function fetchStockAnalysisModels(signal?: AbortSignal) {
  return requestJson<StockAnalysisModel[]>('/stock-analysis', 'Stock analysis', {
    signal,
  })
}

export async function fetchStockAnalysisModel(
  ticker: string,
  signal?: AbortSignal,
) {
  return requestJson<StockAnalysisModel>(
    `/stock-analysis/${tickerPathSegment(ticker)}`,
    'Stock analysis',
    { signal },
  )
}

export async function fetchStockAnalysisCurrentPrice(
  ticker: string,
  signal?: AbortSignal,
) {
  return requestJson<StockAnalysisCurrentPriceResponse>(
    `/stock-analysis/${tickerPathSegment(ticker)}/current-price`,
    'Stock analysis price',
    { signal },
  )
}

export async function refreshStockAnalysisCurrentPrices(signal?: AbortSignal) {
  return requestJson<StockAnalysisPriceRefreshResponse>(
    '/stock-analysis/current-prices/refresh',
    'Stock analysis price refresh',
    {
      method: 'POST',
      signal,
    },
  )
}

export async function upsertStockAnalysisModel(
  ticker: string,
  request: StockAnalysisModelRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<StockAnalysisModel>(
    `/stock-analysis/${tickerPathSegment(ticker)}`,
    'PUT',
    request,
    'Stock analysis',
    signal,
  )
}
