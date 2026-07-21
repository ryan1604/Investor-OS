// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'
import type { PortfolioResponse } from '@/api/portfolio'

const mocks = vi.hoisted(() => ({
  portfolio: null as PortfolioResponse | null,
  loadPortfolio: vi.fn(),
}))

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

vi.mock('@/features/portfolio/hooks/usePortfolio', () => ({
  usePortfolio: () => ({
    portfolio: mocks.portfolio,
    isLoading: false,
    error: null,
    loadPortfolio: mocks.loadPortfolio,
  }),
}))

vi.mock('@/features/orders/hooks/useOrders', () => ({
  useOrders: () => [],
}))

vi.mock('@/features/portfolio/PortfolioPage', () => ({
  PortfolioPage: ({
    selectedAccount,
    onSelectedAccountChange,
  }: {
    selectedAccount: string | null
    onSelectedAccountChange: (account: string) => void
  }) => (
    <main>
      Portfolio route {selectedAccount}
      <button type="button" onClick={() => onSelectedAccountChange('DU2')}>
        Pick DU2 in Portfolio
      </button>
    </main>
  ),
}))

vi.mock('@/features/options/OptionsPage', () => ({
  OptionsPage: ({
    accounts,
    selectedAccount,
    onSelectedAccountChange,
  }: {
    accounts: string[]
    selectedAccount: string | null
    onSelectedAccountChange: (account: string) => void
  }) => (
    <main>
      Options route {selectedAccount}
      <div>Options accounts {accounts.join(',')}</div>
      <button type="button" onClick={() => onSelectedAccountChange('DU1')}>
        Pick DU1 in Options
      </button>
    </main>
  ),
}))

vi.mock('@/features/orders/OrdersPage', () => ({
  OrdersPage: ({
    accounts,
    selectedAccount,
    onSelectedAccountChange,
  }: {
    accounts: string[]
    selectedAccount: string | null
    onSelectedAccountChange: (account: string) => void
  }) => (
    <main>
      Orders route {selectedAccount}
      <div>Orders accounts {accounts.join(',')}</div>
      <button type="button" onClick={() => onSelectedAccountChange('DU2')}>
        Pick DU2 in Orders
      </button>
    </main>
  ),
}))

vi.mock('@/features/options-trade-tracker/OptionsTradeTrackerPage', () => ({
  OptionsTradeTrackerPage: () => <main>Options trade tracker route</main>,
}))

vi.mock('@/features/stock-analysis/StockAnalysisPage', () => ({
  StockAnalysisPage: () => <main>Stock analysis route</main>,
}))

vi.mock('@/features/earnings-watch/EarningsWatchPage', () => ({
  EarningsWatchPage: () => <main>Earnings Watch route</main>,
}))

vi.mock('@/features/rank-stocks/RankStocksPage', () => ({
  RankStocksPage: () => <main>Rank stocks route</main>,
}))

vi.mock('@/features/options-screeners/OptionsScreenersProvider', () => ({
  OptionsScreenersProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/features/options-screeners/CspScreenerPage', () => ({
  CspScreenerPage: () => <main>CSP screener route</main>,
}))

vi.mock('@/features/options-screeners/CcScreenerPage', () => ({
  CcScreenerPage: () => <main>CC screener route</main>,
}))

vi.mock('@/features/options-screeners/CsScreenerPage', () => ({
  CsScreenerPage: () => <main>CS screener route</main>,
}))

afterEach(() => {
  cleanup()
  mocks.portfolio = null
  mocks.loadPortfolio.mockClear()
})

describe('App', () => {
  it('renders Portfolio first and navigates between pages', async () => {
    render(<App />)

    expect(screen.getByText('Portfolio route')).toBeTruthy()
    expect(screen.queryByText('Options route')).toBeNull()

    fireEvent.click(screen.getByText('Options'))
    expect(await screen.findByText('Options route')).toBeTruthy()

    fireEvent.click(screen.getByText('CSP Screener'))
    expect(await screen.findByText('CSP screener route')).toBeTruthy()

    fireEvent.click(screen.getByText('CC Screener'))
    expect(await screen.findByText('CC screener route')).toBeTruthy()

    fireEvent.click(screen.getByText('CS Screener'))
    expect(await screen.findByText('CS screener route')).toBeTruthy()

    fireEvent.click(screen.getByText('Orders'))
    expect(await screen.findByText('Orders route')).toBeTruthy()

    fireEvent.click(screen.getByText('Options Trade Tracker'))
    expect(await screen.findByText('Options trade tracker route')).toBeTruthy()

    fireEvent.click(screen.getByText('Stock Analysis'))
    expect(await screen.findByText('Stock analysis route')).toBeTruthy()

    fireEvent.click(screen.getByText('Earnings Watch'))
    expect(await screen.findByText('Earnings Watch route')).toBeTruthy()

    fireEvent.click(screen.getByText('Rank Stocks'))
    expect(await screen.findByText('Rank stocks route')).toBeTruthy()
  })

  it('shares the first available portfolio account across trading pages', async () => {
    mocks.portfolio = portfolioResponse()

    render(<App />)

    expect(await screen.findByText('Portfolio route DU1')).toBeTruthy()

    fireEvent.click(screen.getByText('Pick DU2 in Portfolio'))
    expect(await screen.findByText('Portfolio route DU2')).toBeTruthy()

    fireEvent.click(screen.getByText('Options'))
    expect(await screen.findByText('Options route DU2')).toBeTruthy()
    expect(screen.getByText('Options accounts DU1,DU2,DU3')).toBeTruthy()

    fireEvent.click(screen.getByText('Pick DU1 in Options'))
    expect(await screen.findByText('Options route DU1')).toBeTruthy()

    fireEvent.click(screen.getByText('Orders'))
    expect(await screen.findByText('Orders route DU1')).toBeTruthy()
    expect(screen.getByText('Orders accounts DU1,DU2,DU3')).toBeTruthy()
  })
})

function portfolioResponse(): PortfolioResponse {
  return {
    status: {
      connected: true,
      host: '127.0.0.1',
      port: 7497,
      client_id: 1,
    },
    accounts: [
      accountSummary('DU2'),
      accountSummary('DU1'),
    ],
    positions: [
      {
        account: 'DU3',
        symbol: 'AAPL',
        sec_type: 'STK',
        local_symbol: null,
        expiry: null,
        strike: null,
        right: null,
        multiplier: null,
        exchange: 'NASDAQ',
        currency: 'USD',
        quantity: 100,
        average_cost: 182.5,
        last_price: 190,
        change_percent: 1.2,
        pnl: 750,
        pnl_percent: 4.1,
        unrealized_pnl: 750,
        unrealized_pnl_percent: 4.1,
        market_value: 19_000,
        cost_basis: 18_250,
        average_price: 182.5,
        net_liquidity: 125_000,
        net_liquidity_percent: 15.2,
      },
    ],
    message: null,
  }
}

function accountSummary(account: string) {
  return {
    account,
    currency: 'USD',
    net_liquidation: 125_000,
    daily_pnl: 450,
    daily_pnl_percent: 0.36,
    unrealized_pnl: 2_400,
    market_value: 18_250,
    maintenance_margin: 8_000,
    excess_liquidity: 117_000,
    buying_power: 468_000,
    cash_total_sgd: 10_000,
    cash_total_usd: 20_000,
    cash_total: 35_000,
  }
}
