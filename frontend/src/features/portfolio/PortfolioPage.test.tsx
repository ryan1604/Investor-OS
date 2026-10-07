// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import { PortfolioPage } from '@/features/portfolio/PortfolioPage'

vi.mock('@/features/portfolio/hooks/usePortfolioQuotes', () => ({
  usePortfolioQuotes: () => undefined,
}))

vi.mock('@/features/portfolio/hooks/usePortfolioChartValues', () => ({
  usePortfolioChartValues: () => ({
    rows: [],
    isLoading: false,
    isSaving: false,
    error: null,
    saveRows: vi.fn(),
  }),
}))

const portfolio: PortfolioResponse = {
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
    },
  ],
  positions: [
    {
      account: 'DU1234567',
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

afterEach(() => {
  cleanup()
})

describe('PortfolioPage', () => {
  it('keeps summary and positions above the chart section', () => {
    render(
      <PortfolioPage
        portfolioState={{
          portfolio,
          isLoading: false,
          error: null,
          loadPortfolio: vi.fn(),
        }}
        selectedAccount="DU1234567"
        onSelectedAccountChange={vi.fn()}
      />,
    )

    const netLiquidation = screen.getByText('Net Liquidation')
    const position = screen.getByText('AAPL')
    const chartSection = screen.getByTestId('portfolio-chart-section')

    expect(netLiquidation.compareDocumentPosition(chartSection)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
    expect(position.compareDocumentPosition(chartSection)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })
})
