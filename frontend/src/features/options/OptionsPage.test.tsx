// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { OptionsPage } from '@/features/options/OptionsPage'
import type { OptionQuoteSelection } from '@/features/options/lib/strategyLegs'

vi.mock('@/features/options/hooks/useOptionsAnalysis', () => ({
  hasAnalysisPriceData: () => true,
  useOptionsAnalysis: () => ({
    analysis: {
      ticker: 'AAPL',
      underlying_price: 190,
      candles: [],
      bollinger_bands: [],
      rsi: [],
      message: null,
    },
    error: null,
    expirations: [{ date: '2026-06-19', days_to_expiration: 16 }],
    expirationsError: null,
    handleSubmit: vi.fn(),
    isExpirationsLoading: false,
    isLoading: false,
    selectedExpiration: '2026-06-19',
    setSelectedExpiration: vi.fn(),
    setTicker: vi.fn(),
    ticker: 'AAPL',
  }),
}))

vi.mock('@/features/options/hooks/useOptionsChartStream', () => ({
  useOptionsChartStream: (analysis: unknown) => ({
    analysis,
    error: null,
    latestUpdate: null,
  }),
}))

vi.mock('@/features/options/hooks/useOptionChain', () => ({
  useOptionChain: () => ({
    chain: { expiration: '2026-06-19', underlying_price: 190, rows: [] },
    chainError: null,
    isChainLoading: false,
  }),
}))

vi.mock('@/features/options/components/OptionsChart', () => ({
  OptionsChart: () => <div>Options chart</div>,
}))

vi.mock('@/features/options/components/RsiChart', () => ({
  RsiChart: () => <div>RSI chart</div>,
}))

vi.mock('@/features/options/components/StockTradeTicket', () => ({
  StockTradeTicket: () => <button type="button">Trade</button>,
}))

vi.mock('@/features/options/components/OptionChainTable', () => ({
  OptionChainTable: ({
    onQuoteClick,
  }: {
    onQuoteClick?: (selection: OptionQuoteSelection) => void
  }) => (
    <button
      type="button"
      onClick={() =>
        onQuoteClick?.({
          ticker: 'AAPL',
          expiration: '2026-06-19',
          right: 'CALL',
          strike: 200,
          action: 'BUY',
          quote: 2.5,
          bid: 2.4,
          ask: 2.5,
        })
      }
    >
      Ask 2.50
    </button>
  ),
}))

vi.mock('@/features/options/components/OptionStrategyTicket', () => ({
  OptionStrategyTicket: ({ open }: { open: boolean }) =>
    open ? <div>Option strategy drawer</div> : null,
}))

afterEach(() => {
  cleanup()
})

describe('OptionsPage', () => {
  it('adds option legs without opening the strategy drawer', async () => {
    render(
      <OptionsPage
        accounts={['DU1234567']}
        orders={[]}
        portfolio={null}
        selectedAccount="DU1234567"
        onSelectedAccountChange={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /^strategy$/i })).toHaveProperty(
      'disabled',
      true,
    )

    fireEvent.click(screen.getByRole('button', { name: /ask 2.50/i }))

    expect(screen.getByRole('button', { name: /strategy \(1\)/i })).toHaveProperty(
      'disabled',
      false,
    )
    expect(screen.queryByText('Option strategy drawer')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /strategy \(1\)/i }))

    expect(await screen.findByText('Option strategy drawer')).toBeTruthy()
  })
})
