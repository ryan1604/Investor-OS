import { formatNumber } from '@/lib/format'

export type OptionContractIdentity = {
  con_id: number | null
  local_symbol: string | null
}

type SingleLegCandidate = {
  ticker: string
  annualized_return: number
  stock_price: number
  strike: number
  expiration: string
  dte: number
  delta: number
  bid: number
  ask: number
  contract: OptionContractIdentity
}

export type CashSecuredPutCandidate = SingleLegCandidate & {
  strategy: 'csp'
  discount_percentage: number
}

export type CoveredCallCandidate = SingleLegCandidate & {
  strategy: 'cc'
  gain_percentage: number
}

export type CreditSpreadCandidate = {
  strategy: 'put_credit_spread' | 'call_credit_spread'
  ticker: string
  annualized_return: number
  stock_price: number
  short_strike: number
  long_strike: number
  expiration: string
  dte: number
  short_delta: number
  net_bid: number
  net_ask: number
  distance_percentage: number
  short_contract: OptionContractIdentity
  long_contract: OptionContractIdentity
}

export type ScreenerCandidate =
  | CashSecuredPutCandidate
  | CoveredCallCandidate
  | CreditSpreadCandidate

export function formatScreenerPrice(value: number) {
  return fixedTwoDecimals(value)
}

export function formatScreenerDelta(value: number) {
  return fixedTwoDecimals(value)
}

export function formatScreenerPercentage(value: number) {
  return `${fixedTwoDecimals(value)}%`
}

function fixedTwoDecimals(value: number) {
  return formatNumber(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}
