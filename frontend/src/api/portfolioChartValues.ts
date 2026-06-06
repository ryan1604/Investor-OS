import { apiUrl, responseErrorMessage } from '@/api/client'

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
  const response = await fetch(apiUrl(portfolioChartValuesPath(account)), {
    signal,
  })

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Portfolio chart values'))
  }

  return response.json() as Promise<PortfolioChartValuesResponse>
}

export async function replacePortfolioChartValues(
  account: string,
  request: PortfolioChartValuesRequest,
  signal?: AbortSignal,
) {
  const response = await fetch(apiUrl(portfolioChartValuesPath(account)), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Portfolio chart values'))
  }

  return response.json() as Promise<PortfolioChartValuesResponse>
}
