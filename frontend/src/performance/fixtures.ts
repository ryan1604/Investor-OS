import type { OptionChainRow, OptionsChartLiveMessage } from '@/api/options'
import type { OrderStatusUpdate } from '@/api/orders'
import type { PortfolioResponse } from '@/api/portfolio'

export const LARGE_PORTFOLIO_POSITION_COUNT = 250
export const LARGE_OPTION_CHAIN_ROW_COUNT = 120
export const CHART_STREAM_UPDATE_COUNT = 260

export function makeLargePortfolioFixture(
  count = LARGE_PORTFOLIO_POSITION_COUNT,
): PortfolioResponse {
  return {
    status: {
      connected: true,
      host: '127.0.0.1',
      port: 7497,
      client_id: 1,
    },
    accounts: [
      {
        account: 'DU1234567',
        currency: 'USD',
        net_liquidation: 250_000,
        daily_pnl: 1_250,
        daily_pnl_percent: 0.5,
        unrealized_pnl: 8_400,
        market_value: 175_000,
        maintenance_margin: 25_000,
        excess_liquidity: 225_000,
        buying_power: 900_000,
        cash_total_sgd: 25_000,
        cash_total_usd: 50_000,
        cash_total: 83_500,
      },
    ],
    positions: Array.from({ length: count }, (_, index) => {
      const isOption = index % 3 !== 0
      const symbol = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'HIMS'][index % 5]
      const quantity = isOption ? (index % 2 === 0 ? 1 : -1) : 100
      const marketValue = 10_000 + index * 17

      return {
        account: 'DU1234567',
        symbol,
        sec_type: isOption ? 'OPT' : 'STK',
        local_symbol: isOption
          ? `${symbol}  260619C${String(180 + (index % 60)).padStart(8, '0')}`
          : null,
        expiry: isOption ? '20260619' : null,
        strike: isOption ? 180 + (index % 60) : null,
        right: isOption ? 'C' : null,
        multiplier: isOption ? '100' : null,
        exchange: 'SMART',
        currency: 'USD',
        quantity,
        average_cost: 150 + (index % 40),
        last_price: 155 + (index % 35),
        change_percent: (index % 9) - 4,
        pnl: (index % 21) * 11.5,
        pnl_percent: (index % 11) - 5,
        unrealized_pnl: (index % 17) * 8.25,
        unrealized_pnl_percent: (index % 13) - 6,
        market_value: marketValue,
        cost_basis: marketValue * 0.92,
        average_price: marketValue / Math.max(Math.abs(quantity), 1),
        net_liquidity: 250_000,
        net_liquidity_percent: (marketValue / 250_000) * 100,
      }
    }),
    message: `Loaded ${count} position(s) from Interactive Brokers.`,
  }
}

export function makeLargeOptionChainFixture(
  count = LARGE_OPTION_CHAIN_ROW_COUNT,
) {
  return {
    ticker: 'AAPL',
    expiration: '2026-06-19',
    underlying_price: 192.5,
    rows: Array.from({ length: count }, (_, index) => {
      const strike = 130 + index * 2.5

      return {
        strike,
        call: makeOptionQuote(strike, index, 'C'),
        put: makeOptionQuote(strike, index, 'P'),
      }
    }),
    message: `Loaded ${count} strike(s) for AAPL 2026-06-19.`,
  }
}

export function makeOptionChainStreamFixture(count = 25) {
  const chain = makeLargeOptionChainFixture()
  const snapshot = {
    type: 'snapshot' as const,
    ticker: chain.ticker,
    expiration: chain.expiration,
    rows: chain.rows,
    message: `Streaming ${chain.rows.length} strike(s).`,
  }
  const updates = chain.rows.slice(0, count).map((row) => ({
    type: 'update' as const,
    ticker: chain.ticker,
    expiration: chain.expiration,
    row,
  }))

  return [snapshot, ...updates] satisfies (
    | {
        type: 'snapshot'
        ticker: string
        expiration: string
        rows: OptionChainRow[]
        message: string
      }
    | {
        type: 'update'
        ticker: string
        expiration: string
        row: OptionChainRow
      }
  )[]
}

export function makeChartStreamFixture(
  count = CHART_STREAM_UPDATE_COUNT,
): OptionsChartLiveMessage[] {
  return Array.from({ length: count }, (_, index) => {
    const close = 180 + (index % 50) * 0.8
    const date = `2026-${String(1 + Math.floor(index / 28)).padStart(
      2,
      '0',
    )}-${String(1 + (index % 28)).padStart(2, '0')}`

    return {
      type: 'update',
      ticker: 'AAPL',
      candle: {
        date,
        open: round(close - 0.7),
        high: round(close + 1.1),
        low: round(close - 1.4),
        close: round(close),
        volume: 1_000_000 + index * 1_000,
      },
      bollinger_band: {
        date,
        upper: round(close + 4),
        middle: round(close),
        lower: round(close - 4),
      },
      rsi: {
        date,
        value: round(45 + (index % 30) * 0.7),
      },
    }
  })
}

export function makePortfolioStreamFixture(count = 10): PortfolioResponse[] {
  return Array.from({ length: count }, (_, index) => {
    const snapshot = makeLargePortfolioFixture()
    snapshot.positions = snapshot.positions.map((position) => ({
      ...position,
      last_price:
        position.last_price === null ? null : round(position.last_price + index * 0.1),
    }))
    return snapshot
  })
}

export function makeOrderStreamFixture(count = 20): OrderStatusUpdate[] {
  return Array.from({ length: count }, (_, index) => ({
    type: 'update',
    orders: null,
    order: {
      order_id: 700 + index,
      perm_id: null,
      parent_order_id: null,
      account: 'DU1234567',
      status: index % 5 === 0 ? 'filled' : 'working',
      editable: true,
      filled: index % 5 === 0 ? 10 : 0,
      remaining: index % 5 === 0 ? 0 : 10,
      avg_fill_price: index % 5 === 0 ? 191.25 : null,
      rejection_message: null,
      submitted_at: '2026-06-05T00:00:00+00:00',
      updated_at: '2026-06-05T00:00:01+00:00',
      preview: {
        preview_id: `fixture-${index}`,
        account: 'DU1234567',
        order_kind: 'stock',
        summary: 'BUY 10 share(s) AAPL',
        time_in_force: 'DAY',
        estimated_order_type: 'LIMIT',
        request: {
          order_kind: 'stock',
          account: 'DU1234567',
          ticker: 'AAPL',
          action: 'BUY',
          quantity: 10,
          order_type: 'LIMIT',
          limit_price: 191.25,
          time_in_force: 'DAY',
        },
      },
    },
  }))
}

function makeOptionQuote(strike: number, index: number, right: 'C' | 'P') {
  const mid = round(0.5 + (index % 25) * 0.18)

  return {
    local_symbol: `AAPL  260619${right}${String(Math.round(strike * 1000)).padStart(
      8,
      '0',
    )}`,
    delta: round(0.1 + (index % 80) / 100),
    bid: round(mid - 0.05),
    bid_size: 10 + index,
    ask: round(mid + 0.05),
    ask_size: 12 + index,
    mid,
    last: mid,
    close: round(mid - 0.02),
    model_price: round(mid + 0.01),
    change_percent: round((index % 12) - 6),
    volume: 100 + index * 3,
    open_interest: 1_000 + index * 7,
    gamma: round(0.01 + (index % 10) / 1_000, 4),
    theta: round(-0.01 - (index % 10) / 1_000, 4),
    implied_volatility_percent: round(35 + (index % 20) * 0.4),
    breakeven: round(right === 'C' ? strike + mid : strike - mid),
  }
}

function round(value: number, digits = 2) {
  const scale = 10 ** digits
  return Math.round(value * scale) / scale
}
