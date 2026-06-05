import { apiUrl, responseErrorMessage, tickerPathSegment } from '@/api/client'

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

export async function fetchStockAnalysisModel(
  ticker: string,
  signal?: AbortSignal,
) {
  const response = await fetch(
    apiUrl(`/stock-analysis/${tickerPathSegment(ticker)}`),
    { signal },
  )

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Stock analysis'))
  }

  return response.json() as Promise<StockAnalysisModel>
}

export async function fetchStockAnalysisCurrentPrice(
  ticker: string,
  signal?: AbortSignal,
) {
  const response = await fetch(
    apiUrl(`/stock-analysis/${tickerPathSegment(ticker)}/current-price`),
    { signal },
  )

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Stock analysis price'))
  }

  return response.json() as Promise<StockAnalysisCurrentPriceResponse>
}

export async function upsertStockAnalysisModel(
  ticker: string,
  request: StockAnalysisModelRequest,
  signal?: AbortSignal,
) {
  const response = await fetch(
    apiUrl(`/stock-analysis/${tickerPathSegment(ticker)}`),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    },
  )

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Stock analysis'))
  }

  return response.json() as Promise<StockAnalysisModel>
}
