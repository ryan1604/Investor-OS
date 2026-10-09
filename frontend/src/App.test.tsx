// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'
import { fetchOrders } from '@/api/orders'
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

vi.mock('@/api/orders', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/orders')>(),
  fetchOrders: vi.fn(() => new Promise(() => undefined)),
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

vi.mock('@/features/portfolio-analysis/PortfolioAnalysisPage', () => ({
  PortfolioAnalysisPage: ({ selectedAccount }: { selectedAccount: string | null }) => (
    <main>Portfolio analysis route {selectedAccount}</main>
  ),
}))

vi.mock('@/features/options/OptionsPage', () => ({
  OptionsPage: ({
    accounts,
    isActive,
    selectedAccount,
    onSelectedAccountChange,
  }: {
    accounts: string[]
    isActive: boolean
    selectedAccount: string | null
    onSelectedAccountChange: (account: string) => void
  }) => (
    <main>
      Options route {selectedAccount}
      <input aria-label="Options ticker" defaultValue="" />
      <div>Options is {isActive ? 'active' : 'inactive'}</div>
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

vi.mock('@/features/day-trading-tracker/DayTradingTrackerPage', () => ({
  DayTradingTrackerPage: () => <main>Day trading tracker route</main>,
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

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  close() {
    this.closed = true
    this.onclose?.()
  }
}

beforeEach(() => {
  FakeWebSocket.sockets = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  vi.mocked(fetchOrders).mockClear()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  mocks.portfolio = null
  mocks.loadPortfolio.mockClear()
})

describe('App', () => {
  it('shares one order connection when Options has been visited and Orders is active', () => {
    const { unmount } = render(<App />)
    expect(FakeWebSocket.sockets).toHaveLength(0)
    expect(fetchOrders).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Options' }))
    expect(FakeWebSocket.sockets).toHaveLength(1)
    const [socket] = FakeWebSocket.sockets
    expect(new URL(socket.url).pathname).toBe('/orders/ws')

    fireEvent.click(screen.getByRole('button', { name: 'Orders' }))
    expect(screen.getByTestId('options-workspace').hasAttribute('hidden')).toBe(true)
    expect(screen.getByText('Orders route')).toBeTruthy()
    expect(FakeWebSocket.sockets).toHaveLength(1)
    expect(socket.closed).toBe(false)
    expect(fetchOrders).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Portfolio' }))
    expect(socket.closed).toBe(false)
    unmount()
    expect(socket.closed).toBe(true)
  })

  it('opens orders only while Orders is active before the first Options visit', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Orders' }))
    expect(FakeWebSocket.sockets).toHaveLength(1)
    expect(fetchOrders).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Portfolio' }))
    expect(FakeWebSocket.sockets[0].closed).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Orders' }))
    expect(FakeWebSocket.sockets).toHaveLength(2)
    expect(fetchOrders).toHaveBeenCalledTimes(2)
  })

  it('renders Portfolio first and navigates between pages', async () => {
    render(<App />)

    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeTruthy()
    expect(screen.getByText('Portfolio route')).toBeTruthy()
    expect(screen.queryByText('Options route')).toBeNull()
    expect(screen.getByRole('button', { name: 'Portfolio' }).getAttribute('aria-current')).toBe('page')

    fireEvent.click(screen.getByRole('button', { name: 'Portfolio Analysis' }))
    expect(await screen.findByText('Portfolio analysis route')).toBeTruthy()
    expect(
      screen.getByRole('button', { name: 'Portfolio Analysis' }).getAttribute('aria-current'),
    ).toBe('page')

    fireEvent.click(screen.getByRole('button', { name: 'Options' }))
    expect(await screen.findByText('Options route')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Options' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('button', { name: 'Portfolio' }).getAttribute('aria-current')).toBeNull()

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

    fireEvent.click(screen.getByText('Day Trading Tracker'))
    expect(await screen.findByText('Day trading tracker route')).toBeTruthy()

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

  it('retains a saved-only Portfolio account while trading uses live accounts', async () => {
    mocks.portfolio = { ...portfolioResponse(), accounts: [accountSummary('DU1')], positions: [] }
    const { rerender } = render(<App />)
    fireEvent.click(screen.getByText('Pick DU2 in Portfolio'))
    expect(screen.getByText('Portfolio route DU2')).toBeTruthy()

    mocks.portfolio = { ...mocks.portfolio }
    rerender(<App />)
    expect(screen.getByText('Portfolio route DU2')).toBeTruthy()
    fireEvent.click(screen.getByText('Options'))
    expect(await screen.findByText('Options route DU1')).toBeTruthy()
    expect(screen.getByText('Options accounts DU1')).toBeTruthy()
    fireEvent.click(screen.getByText('Orders'))
    expect(await screen.findByText('Orders route DU1')).toBeTruthy()
    expect(screen.getByText('Orders accounts DU1')).toBeTruthy()
    fireEvent.click(screen.getByText('Portfolio'))
    expect(screen.getByText('Portfolio route DU2')).toBeTruthy()

    mocks.portfolio = { ...mocks.portfolio, accounts: [] }
    rerender(<App />)
    fireEvent.click(screen.getByText('Orders'))
    expect(await screen.findByText('Orders route')).toBeTruthy()
    fireEvent.click(screen.getByText('Portfolio'))
    expect(screen.getByText('Portfolio route DU2')).toBeTruthy()
  })

  it('keeps the selected Portfolio account when TWS disconnects', async () => {
    mocks.portfolio = portfolioResponse()
    const { rerender } = render(<App />)
    fireEvent.click(await screen.findByText('Pick DU2 in Portfolio'))
    expect(await screen.findByText('Portfolio route DU2')).toBeTruthy()
    mocks.portfolio = { ...portfolioResponse(),
      status: { ...portfolioResponse().status, connected: false },
      accounts: [], positions: [],
    }
    rerender(<App />)
    expect(screen.getByText('Portfolio route DU2')).toBeTruthy()
  })

  it('retains the Options workspace after its first visit', async () => {
    render(<App />)

    expect(screen.queryByTestId('options-workspace')).toBeNull()

    fireEvent.click(screen.getByText('Options'))
    const tickerInput = await screen.findByLabelText('Options ticker')
    fireEvent.change(tickerInput, { target: { value: 'HIMS' } })

    fireEvent.click(screen.getByText('Portfolio'))

    const hiddenWorkspace = screen.getByTestId('options-workspace')
    expect(hiddenWorkspace.hasAttribute('hidden')).toBe(true)
    expect(screen.getByText('Options is inactive')).toBeTruthy()

    fireEvent.click(screen.getByText('Options'))

    expect(hiddenWorkspace.hasAttribute('hidden')).toBe(false)
    expect(screen.getByText('Options is active')).toBeTruthy()
    expect((screen.getByLabelText('Options ticker') as HTMLInputElement).value).toBe(
      'HIMS',
    )
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
