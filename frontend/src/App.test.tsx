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

vi.mock('@/features/stock-analysis/StockAnalysisPage', () => ({
  StockAnalysisPage: () => <main>Stock analysis route</main>,
}))

afterEach(() => {
  cleanup()
})

describe('App', () => {
  it('renders Portfolio first and navigates to lazy-loaded pages', async () => {
    render(<App />)

    expect(screen.getByText('Portfolio route')).toBeTruthy()
    expect(screen.queryByText('Options route')).toBeNull()

    fireEvent.click(screen.getByText('Options'))
    expect(await screen.findByText('Options route')).toBeTruthy()

    fireEvent.click(screen.getByText('Orders'))
    expect(await screen.findByText('Orders route')).toBeTruthy()

    fireEvent.click(screen.getByText('Stock analysis'))
    expect(await screen.findByText('Stock analysis route')).toBeTruthy()
  })
})
