// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'

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
    portfolio: null,
    isLoading: false,
    error: null,
    loadPortfolio: vi.fn(),
  }),
}))

vi.mock('@/features/orders/hooks/useOrders', () => ({
  useOrders: () => [],
}))

vi.mock('@/features/portfolio/PortfolioPage', () => ({
  PortfolioPage: () => <main>Portfolio route</main>,
}))

vi.mock('@/features/options/OptionsPage', () => ({
  OptionsPage: () => <main>Options route</main>,
}))

vi.mock('@/features/orders/OrdersPage', () => ({
  OrdersPage: () => <main>Orders route</main>,
}))

vi.mock('@/features/options-trade-tracker/OptionsTradeTrackerPage', () => ({
  OptionsTradeTrackerPage: () => <main>Options trade tracker route</main>,
}))

vi.mock('@/features/stock-analysis/StockAnalysisPage', () => ({
  StockAnalysisPage: () => <main>Stock analysis route</main>,
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

    fireEvent.click(screen.getByText('Rank Stocks'))
    expect(await screen.findByText('Rank stocks route')).toBeTruthy()
  })
})
