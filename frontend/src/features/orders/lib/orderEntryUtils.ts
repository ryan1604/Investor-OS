import type { PortfolioResponse } from '@/api/portfolio'

export function accountOptions(portfolio: PortfolioResponse | null) {
  return portfolioAccounts(portfolio).map((account) => ({
    label: account,
    value: account,
  }))
}

export function portfolioAccounts(portfolio: PortfolioResponse | null) {
  return Array.from(
    new Set([
      ...(portfolio?.accounts.map((account) => account.account) ?? []),
      ...(portfolio?.positions.map((position) => position.account) ?? []),
    ]),
  ).sort()
}

export function parsePositiveNumber(value: string) {
  if (!value.trim()) {
    return null
  }
  const parsedValue = Number(value)
  return Number.isFinite(parsedValue) && parsedValue > 0 ? parsedValue : null
}

export function parsePositiveInteger(value: string) {
  const parsedValue = Number(value)
  return Number.isInteger(parsedValue) && parsedValue > 0 ? parsedValue : null
}

export function parseSignedNumber(value: string) {
  if (!value.trim()) {
    return null
  }
  const parsedValue = Number(value)
  return Number.isFinite(parsedValue) ? parsedValue : null
}

export function orderErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Order request failed.'
}
