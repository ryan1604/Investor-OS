// @vitest-environment jsdom

import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  OptionChainResponse,
  OptionQuote,
  OptionsAnalysisResponse,
} from '@/api/options'
import { OptionChainTable } from '@/features/options/components/OptionChainTable'

afterEach(() => {
  cleanup()
})

const analysis: OptionsAnalysisResponse = {
  ticker: 'SOFI',
  underlying_price: 103,
  candles: [],
  bollinger_bands: [],
  rsi: [],
  message: null,
}

const chain: OptionChainResponse = {
  ticker: 'SOFI',
  expiration: '2026-06-19',
  underlying_price: 100,
  rows: [
    { strike: 95, call: null, put: null },
    { strike: 105, call: null, put: null },
  ],
  message: null,
}

function quote(overrides: Partial<OptionQuote>): OptionQuote {
  return {
    local_symbol: null,
    delta: null,
    bid: null,
    bid_size: null,
    ask: null,
    ask_size: null,
    mid: null,
    last: null,
    close: null,
    model_price: null,
    change_percent: null,
    volume: null,
    open_interest: null,
    gamma: null,
    theta: null,
    implied_volatility_percent: null,
    breakeven: null,
    ...overrides,
  }
}

describe('OptionChainTable', () => {
  it('anchors the calls pane to the strike side by default', () => {
    const { container } = render(
      <OptionChainTable
        analysis={analysis}
        chain={chain}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    const scrollers = container.querySelectorAll('.overflow-x-auto')

    expect(scrollers[0].getAttribute('dir')).toBe('rtl')
    expect(scrollers[1].getAttribute('dir')).toBeNull()
  })

  it('shows the chain stream warning', () => {
    render(
      <OptionChainTable
        analysis={analysis}
        chain={{ ...chain, warning: 'Waiting for free IB market-data lines.' }}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    expect(
      screen.getByText('Waiting for free IB market-data lines.'),
    ).toBeTruthy()
  })

  it('uses the live chart price and keeps quote and strike rows the same height', () => {
    const { container } = render(
      <OptionChainTable
        analysis={analysis}
        chain={chain}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    expect(screen.getByText('103.00')).toBeTruthy()
    expect(screen.queryByText('100.00')).toBeNull()

    const quoteCell = container.querySelector('table:first-child tbody td')
    const strikeCell = screen.getByText('95.00').closest('td')

    expect(quoteCell?.className).toContain('h-14')
    expect(strikeCell?.className).toContain('h-14')
  })

  it('shows call and put return percentages between mid and last', () => {
    const chainWithQuotes: OptionChainResponse = {
      ...chain,
      rows: [
        {
          strike: 95,
          call: quote({ mid: 2.575, last: 2.6 }),
          put: quote({ mid: 1.9, last: 1.95 }),
        },
      ],
    }

    const { container } = render(
      <OptionChainTable
        analysis={analysis}
        chain={chainWithQuotes}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    expect(screen.getAllByText('Return %')).toHaveLength(2)

    const [callTable, , putTable] = Array.from(container.querySelectorAll('table'))
    const callRow = within(callTable).getByText('2.50%').closest('tr')
    const putRow = within(putTable).getByText('2.00%').closest('tr')
    const callValues = Array.from(callRow?.querySelectorAll('td') ?? []).map(
      (cell) => cell.textContent?.trim(),
    )
    const putValues = Array.from(putRow?.querySelectorAll('td') ?? []).map(
      (cell) => cell.textContent?.trim(),
    )

    expect(callValues.slice(9, 12)).toEqual(['2.60', '2.50%', '2.58'])
    expect(putValues.slice(3, 6)).toEqual(['1.90', '2.00%', '1.95'])
  })

  it('recalculates call return from the latest underlying price', () => {
    const chainWithQuotes: OptionChainResponse = {
      ...chain,
      rows: [
        {
          strike: 95,
          call: quote({ mid: 2.575 }),
          put: null,
        },
      ],
    }

    const { rerender } = render(
      <OptionChainTable
        analysis={analysis}
        chain={chainWithQuotes}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    expect(screen.getByText('2.50%')).toBeTruthy()

    rerender(
      <OptionChainTable
        analysis={{ ...analysis, underlying_price: 206 }}
        chain={chainWithQuotes}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    expect(screen.getByText('1.25%')).toBeTruthy()
    expect(screen.queryByText('2.50%')).toBeNull()
  })

  it('renders missing return percentages as placeholders', () => {
    const chainWithQuotes: OptionChainResponse = {
      ...chain,
      rows: [
        {
          strike: 95,
          call: quote({ mid: null }),
          put: quote({ mid: null }),
        },
      ],
    }

    const { container } = render(
      <OptionChainTable
        analysis={{ ...analysis, underlying_price: null }}
        chain={chainWithQuotes}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />,
    )

    const [callTable, , putTable] = Array.from(container.querySelectorAll('table'))
    const callValues = Array.from(
      callTable.querySelector('tbody tr')?.querySelectorAll('td') ?? [],
    ).map((cell) => cell.textContent?.trim())
    const putValues = Array.from(
      putTable.querySelector('tbody tr')?.querySelectorAll('td') ?? [],
    ).map((cell) => cell.textContent?.trim())

    expect(callValues[10]).toBe('-')
    expect(putValues[4]).toBe('-')
  })

  it('maps ask clicks to buy legs and bid clicks to sell legs', () => {
    const onQuoteClick = vi.fn()
    const chainWithQuotes: OptionChainResponse = {
      ...chain,
      rows: [
        {
          strike: 95,
          call: quote({ bid: 2.4, ask: 2.6, local_symbol: 'AAPL 95C' }),
          put: quote({ bid: 1.8, ask: 2, local_symbol: 'AAPL 95P' }),
        },
      ],
    }

    render(
      <OptionChainTable
        analysis={analysis}
        chain={chainWithQuotes}
        error={null}
        isLoading={false}
        onQuoteClick={onQuoteClick}
        selectedExpiration={chain.expiration}
      />,
    )

    screen.getByRole('button', { name: '2.60' }).click()
    screen.getByRole('button', { name: '1.80' }).click()

    expect(onQuoteClick).toHaveBeenNthCalledWith(1, {
      ticker: 'SOFI',
      expiration: '2026-06-19',
      right: 'CALL',
      strike: 95,
      action: 'BUY',
      quote: 2.6,
      bid: 2.4,
      ask: 2.6,
    })
    expect(onQuoteClick).toHaveBeenNthCalledWith(2, {
      ticker: 'SOFI',
      expiration: '2026-06-19',
      right: 'PUT',
      strike: 95,
      action: 'SELL',
      quote: 1.8,
      bid: 1.8,
      ask: 2,
    })
  })
})
