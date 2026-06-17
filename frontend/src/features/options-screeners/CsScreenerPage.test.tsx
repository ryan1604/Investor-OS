// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import * as api from '@/api/optionsScreeners'
import { CsScreenerPage } from '@/features/options-screeners/CsScreenerPage'

vi.mock('@/api/optionsScreeners', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/optionsScreeners')>()
  return { ...actual, refreshOptionsScreenerSpreadQuote: vi.fn() }
})

vi.mock('@/features/options-screeners/OptionsScreenersProvider', async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import('@/features/options-screeners/OptionsScreenersProvider')
    >()
  return { ...actual, useOptionsScreeners: () => state }
})

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 43,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        size: 43,
        start: index * 43,
      })),
  }),
}))

const candidate = {
  strategy: 'put_credit_spread' as const,
  ticker: 'TSLA',
  annualized_return: 40,
  stock_price: 100,
  short_strike: 95,
  long_strike: 90,
  expiration: '2026-07-17',
  dte: 30,
  short_delta: -0.2,
  net_bid: 1,
  net_ask: 1.2,
  distance_percentage: 5,
  short_contract: { con_id: 123, local_symbol: 'TSLA SHORT PUT' },
  long_contract: { con_id: 124, local_symbol: 'TSLA LONG PUT' },
}

const snapshot = {
  screener: 'cs' as const,
  job_id: 'cs-job',
  total_match_count: 2,
  excluded_contracts: 0,
  candidates: [candidate],
  errors: [],
  warnings: [],
  completed_at: '2026-06-15T00:00:00Z',
}

const state = {
  isLoading: false,
  loadError: null,
  csTickers: ['TSLA'],
  csFilterDraft: {
    minimum_dte: '7',
    maximum_dte: '45',
    minimum_absolute_delta: '0.15',
    maximum_absolute_delta: '0.3',
    minimum_annualized_return: '10',
    strategy_types: ['put_credit_spread' as const, 'call_credit_spread' as const],
    spread_widths: [5 as const],
  },
  csFilters: {
    version: 1,
    minimum_dte: 7,
    maximum_dte: 45,
    minimum_absolute_delta: 0.15,
    maximum_absolute_delta: 0.3,
    minimum_annualized_return: 10,
    strategy_types: ['put_credit_spread' as const, 'call_credit_spread' as const],
    spread_widths: [5 as const],
  },
  csFilterError: null,
  csFilterSaveStatus: 'saved' as const,
  tickerSaveError: null,
  isTickerUpdatePending: false,
  scanActionError: null,
  activeJob: null,
  csSnapshot: snapshot,
  csSort: { key: 'annualized_return' as const, direction: 'desc' as const },
  addCsTickers: vi.fn(),
  removeCsTicker: vi.fn(),
  clearCsTickers: vi.fn(),
  updateCsFilterDraft: vi.fn(),
  toggleCsStrategyType: vi.fn(),
  toggleCsSpreadWidth: vi.fn(),
  resetCsFilters: vi.fn(),
  startCsScan: vi.fn(),
  cancelActiveScan: vi.fn(),
  setCsSort: vi.fn(),
}

const portfolio: PortfolioResponse = {
  status: {
    connected: true,
    host: '127.0.0.1',
    port: 7497,
    client_id: 1,
  },
  accounts: [
    {
      account: 'DU222',
      currency: 'USD',
      net_liquidation: null,
      daily_pnl: null,
      daily_pnl_percent: null,
      unrealized_pnl: null,
      market_value: null,
      maintenance_margin: null,
      excess_liquidity: null,
      buying_power: null,
      cash_total_sgd: null,
      cash_total_usd: null,
      cash_total: null,
    },
  ],
  positions: [],
  message: null,
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.clearAllMocks()
  Object.assign(state, {
    activeJob: null,
    csSnapshot: snapshot,
    csFilterError: null,
    csFilterDraft: {
      ...state.csFilterDraft,
      strategy_types: ['put_credit_spread', 'call_credit_spread'],
      spread_widths: [5],
    },
  })
})

describe('CsScreenerPage', () => {
  it('uses separate CS tickers, filters, scan action, and spread columns', () => {
    render(<CsScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByRole('heading', { name: 'Credit Spread Screener' })).toBeTruthy()
    expect(screen.getAllByText('TSLA').length).toBeGreaterThan(1)
    expect(
      screen.getByRole('button', { name: /Strategy/i }),
    ).toBeTruthy()
    expect(screen.getByText('Short Strike')).toBeTruthy()
    expect(screen.getByText('Long Strike')).toBeTruthy()
    expect(screen.getByText('Net Bid')).toBeTruthy()
    expect(screen.getByText('Distance %')).toBeTruthy()
    expect(screen.getByText('Put credit')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Minimum DTE'), {
      target: { value: '14' },
    })
    expect(state.updateCsFilterDraft).toHaveBeenCalledWith('minimum_dte', '14')

    fireEvent.click(screen.getByLabelText('Put credit spread'))
    expect(state.toggleCsStrategyType).toHaveBeenCalledWith('put_credit_spread')

    fireEvent.click(screen.getByLabelText('$10'))
    expect(state.toggleCsSpreadWidth).toHaveBeenCalledWith(10)

    fireEvent.click(screen.getByRole('button', { name: /scan 1 ticker/i }))
    expect(state.startCsScan).toHaveBeenCalled()
  })

  it('disables scan and shows validation when strategy or width is empty', () => {
    Object.assign(state, {
      csFilterError: 'Select at least one spread width.',
      csFilterDraft: {
        ...state.csFilterDraft,
        spread_widths: [],
      },
    })

    render(<CsScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('Select at least one spread width.')).toBeTruthy()
    expect(
      screen.getByRole('button', { name: /scan 1 ticker/i }).hasAttribute('disabled'),
    ).toBe(true)
  })

  it('prompts for scan before a snapshot and shows no matches after empty snapshot', () => {
    Object.assign(state, { csSnapshot: null })
    const { rerender } = render(
      <CsScreenerPage portfolio={null} selectedAccount={null} />,
    )

    expect(screen.getByText('Start a scan')).toBeTruthy()

    Object.assign(state, {
      csSnapshot: { ...snapshot, total_match_count: 0, candidates: [] },
    })
    rerender(<CsScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('No matching spreads')).toBeTruthy()
  })

  it('retains completed rows while a CS scan is active and supports cancellation', () => {
    Object.assign(state, {
      activeJob: {
        id: 'active-cs',
        screener: 'cs',
        status: 'active',
        tickers: ['TSLA', 'AAPL'],
        filters: state.csFilters,
        total_tickers: 2,
        completed_tickers: 1,
        progress_message: '1 of 2 tickers scanned',
        successful_tickers: 1,
        no_match_tickers: 0,
        failed_tickers: 0,
        total_match_count: 0,
        excluded_contracts: 0,
        candidates: [],
        errors: [],
        warnings: [],
        started_at: '2026-06-15T00:00:00Z',
        finished_at: null,
        successful_completion_at: null,
      },
    })

    render(<CsScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('Scan in progress')).toBeTruthy()
    expect(screen.getByText('1 of 2 tickers scanned')).toBeTruthy()
    expect(screen.getAllByText('TSLA').length).toBeGreaterThan(1)
    fireEvent.click(screen.getByRole('button', { name: /cancel scan/i }))
    expect(state.cancelActiveScan).toHaveBeenCalled()
  })

  it('refreshes both legs before opening a signed two-leg put spread ticket', async () => {
    vi.mocked(api.refreshOptionsScreenerSpreadQuote).mockResolvedValue({
      strategy: 'put_credit_spread',
      ticker: 'TSLA',
      expiration: '2026-07-17',
      right: 'PUT',
      short_strike: 95,
      long_strike: 90,
      short_contract: { con_id: 456, local_symbol: 'TSLA REFRESHED SHORT PUT' },
      long_contract: { con_id: 457, local_symbol: 'TSLA REFRESHED LONG PUT' },
      short_bid: 2.1,
      short_ask: 2.3,
      short_midpoint: 2.2,
      long_bid: 0.9,
      long_ask: 1,
      long_midpoint: 0.95,
      short_delta: -0.2,
      net_bid: 1.1,
      net_ask: 1.4,
      net_midpoint: 1.25,
      maximum_loss: 3.75,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(
      <CsScreenerPage
        portfolio={portfolio}
        selectedAccount="DU222"
      />,
    )
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(await screen.findByText('Option strategy')).toBeTruthy()
    expect(api.refreshOptionsScreenerSpreadQuote).toHaveBeenCalledWith({
      strategy: 'put_credit_spread',
      ticker: 'TSLA',
      expiration: '2026-07-17',
      short_strike: 95,
      long_strike: 90,
      short_contract: candidate.short_contract,
      long_contract: candidate.long_contract,
    })
    expect((screen.getByLabelText('Quantity 95 PUT') as HTMLInputElement).value).toBe('-1')
    expect((screen.getByLabelText('Quantity 90 PUT') as HTMLInputElement).value).toBe('1')
    expect((screen.getByLabelText('Net limit credit') as HTMLInputElement).value).toBe('1.25')
    expect(screen.getByText('Sell')).toBeTruthy()
    expect(screen.getByText('Buy')).toBeTruthy()
    expect(screen.queryByText('Select an account.')).toBeNull()
  })

  it('opens a refreshed call spread ticket with call-side quantities', async () => {
    const callCandidate = {
      ...candidate,
      strategy: 'call_credit_spread' as const,
      short_strike: 105,
      long_strike: 110,
      short_delta: 0.2,
    }
    Object.assign(state, {
      csSnapshot: {
        ...snapshot,
        candidates: [callCandidate],
      },
    })
    vi.mocked(api.refreshOptionsScreenerSpreadQuote).mockResolvedValue({
      strategy: 'call_credit_spread',
      ticker: 'TSLA',
      expiration: '2026-07-17',
      right: 'CALL',
      short_strike: 105,
      long_strike: 110,
      short_contract: { con_id: 556, local_symbol: 'TSLA REFRESHED SHORT CALL' },
      long_contract: { con_id: 557, local_symbol: 'TSLA REFRESHED LONG CALL' },
      short_bid: 2.1,
      short_ask: 2.3,
      short_midpoint: 2.2,
      long_bid: 0.9,
      long_ask: 1,
      long_midpoint: 0.95,
      short_delta: 0.2,
      net_bid: 1.1,
      net_ask: 1.4,
      net_midpoint: 1.25,
      maximum_loss: 3.75,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(<CsScreenerPage portfolio={portfolio} selectedAccount="DU222" />)
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(await screen.findByText('Option strategy')).toBeTruthy()
    expect((screen.getByLabelText('Quantity 105 CALL') as HTMLInputElement).value).toBe('-1')
    expect((screen.getByLabelText('Quantity 110 CALL') as HTMLInputElement).value).toBe('1')
  })

  it('blocks stale tickets when spread refresh fails', async () => {
    vi.mocked(api.refreshOptionsScreenerSpreadQuote).mockRejectedValue(
      new Error('The selected spread no longer has a valid net-credit market.'),
    )

    render(<CsScreenerPage portfolio={null} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(
      await screen.findByText(
        'The selected spread no longer has a valid net-credit market.',
      ),
    ).toBeTruthy()
    expect(screen.queryByText('Option strategy')).toBeNull()
  })

  it('warns but opens when refreshed spread misses current filters', async () => {
    vi.mocked(api.refreshOptionsScreenerSpreadQuote).mockResolvedValue({
      strategy: 'put_credit_spread',
      ticker: 'TSLA',
      expiration: '2026-07-17',
      right: 'PUT',
      short_strike: 95,
      long_strike: 90,
      short_contract: { con_id: 456, local_symbol: 'TSLA REFRESHED SHORT PUT' },
      long_contract: { con_id: 457, local_symbol: 'TSLA REFRESHED LONG PUT' },
      short_bid: 2.1,
      short_ask: 2.3,
      short_midpoint: 2.2,
      long_bid: 0.9,
      long_ask: 1,
      long_midpoint: 0.95,
      short_delta: -0.5,
      net_bid: 1.1,
      net_ask: 1.4,
      net_midpoint: 1.25,
      maximum_loss: 3.75,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(<CsScreenerPage portfolio={portfolio} selectedAccount="DU222" />)
    fireEvent.click(screen.getAllByRole('row')[1])

    await waitFor(() => {
      expect(
        screen.getByText(
          'The refreshed spread no longer satisfies the current CS scan filters, exact width, or maximum-loss rules.',
        ),
      ).toBeTruthy()
    })
    expect(screen.getByText('Option strategy')).toBeTruthy()
  })
})
