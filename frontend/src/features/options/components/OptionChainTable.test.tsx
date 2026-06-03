// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type {
  OptionChainResponse,
  OptionsAnalysisResponse,
} from '@/api/options'
import { OptionChainTable } from '@/features/options/components/OptionChainTable'

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

describe('OptionChainTable', () => {
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
})
