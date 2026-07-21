import { jsonRequest, requestJson } from '@/api/client'

export type PortfolioChartValue = {
  month: string
  portfolio_value: number | null
  amount_invested: number | null
  updated_at: string
}

export type PortfolioChartValuesResponse = {
  account: string
  rows: PortfolioChartValue[]
}

export type PortfolioChartValueRequest = {
  month: string
  portfolio_value?: number | null
  amount_invested?: number | null
}

export type PortfolioChartValuesRequest = {
  rows: PortfolioChartValueRequest[]
}

export function portfolioChartValuesPath(account: string) {
  const normalizedAccount = account.trim().toUpperCase()

  if (!normalizedAccount) {
    throw new Error('Account is required.')
  }

  return `/portfolio/chart-values?${new URLSearchParams({
    account: normalizedAccount,
  })}`
}

export async function fetchPortfolioChartValues(
  account: string,
  signal?: AbortSignal,
) {
  return requestJson<PortfolioChartValuesResponse>(
    portfolioChartValuesPath(account),
    'Portfolio chart values',
    { signal },
  )
}

export async function replacePortfolioChartValues(
  account: string,
  request: PortfolioChartValuesRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<PortfolioChartValuesResponse>(
    portfolioChartValuesPath(account),
    'PUT',
    request,
    'Portfolio chart values',
    signal,
  )
}
