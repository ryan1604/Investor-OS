import { apiWebSocketUrl, requestJson } from '@/api/client'

export type IbStatus = {
  connected: boolean
  host: string
  port: number
  client_id: number
}

export type PortfolioPosition = {
  account: string
  symbol: string
  sec_type: string
  local_symbol: string | null
  expiry: string | null
  strike: number | null
  right: string | null
  multiplier: string | null
  exchange: string
  currency: string
  quantity: number
  average_cost: number | null
  last_price: number | null
  change_percent: number | null
  pnl: number | null
  pnl_percent: number | null
  unrealized_pnl: number | null
  unrealized_pnl_percent: number | null
  market_value: number | null
  cost_basis: number | null
  average_price: number | null
  net_liquidity: number | null
  net_liquidity_percent: number | null
}

export type PortfolioAccountSummary = {
  account: string
  currency: string
  net_liquidation: number | null
  daily_pnl: number | null
  daily_pnl_percent: number | null
  unrealized_pnl: number | null
  market_value: number | null
  maintenance_margin: number | null
  excess_liquidity: number | null
  buying_power: number | null
  cash_total_sgd: number | null
  cash_total_usd: number | null
  cash_total: number | null
}

export type PortfolioResponse = {
  status: IbStatus
  accounts: PortfolioAccountSummary[]
  positions: PortfolioPosition[]
  message: string | null
}

export const PORTFOLIO_WS_URL = apiWebSocketUrl('/portfolio/ws')

export async function fetchPortfolio() {
  return requestJson<PortfolioResponse>('/portfolio', 'Portfolio')
}
