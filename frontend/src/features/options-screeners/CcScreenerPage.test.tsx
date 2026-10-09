// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import * as api from '@/api/optionsScreeners'
import { CcScreenerPage } from '@/features/options-screeners/CcScreenerPage'

vi.mock('@/api/optionsScreeners', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/optionsScreeners')>()
  return { ...actual, refreshOptionsScreenerQuote: vi.fn() }
})

vi.mock('@/features/options-screeners/hooks/useOptionsScreeners', async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import('@/features/options-screeners/hooks/useOptionsScreeners')
    >()
  return {
    ...actual,
    useOptionsScreeners: () => ({
      ...state,
      screeners: {
        cc: {
          filterDraft: state.ccFilterDraft,
          filters: state.ccFilters,
          filterError: state.ccFilterError,
          filterSaveStatus: state.ccFilterSaveStatus,
          snapshot: state.ccSnapshot,
          sort: state.ccSort,
          updateFilterDraft: state.updateCcFilterDraft,
          resetFilters: state.resetCcFilters,
          startScan: state.startCcScan,
          setSort: state.setCcSort,
          tickers: state.cspTickers,
          addTickers: state.addCspTickers,
          removeTicker: state.removeCspTicker,
          clearTickers: state.clearCspTickers,
        },
        csp: {
          tickers: state.cspTickers,
          addTickers: state.addCspTickers,
          removeTicker: state.removeCspTicker,
          clearTickers: state.clearCspTickers,
        },
      },
    }),
  }
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
  strategy: 'cc' as const,
  ticker: 'AAPL',
  annualized_return: 20,
  stock_price: 100,
  strike: 110,
  expiration: '2026-07-17',
  dte: 32,
  delta: 0.2,
  bid: 1,
  ask: 1.2,
  gain_percentage: 10,
  contract: { con_id: 123, local_symbol: 'AAPL CALL' },
}

const snapshot = {
  screener: 'cc' as const,
  job_id: 'cc-job',
  total_match_count: 1,
  excluded_contracts: 0,
  candidates: [candidate],
  errors: [],
  warnings: [],
  completed_at: '2026-06-15T00:00:00Z',
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

const state = {
  isLoading: false,
  loadError: null,
  cspTickers: ['AAPL'],
  ccFilterDraft: {
    minimum_dte: '7',
    maximum_dte: '45',
    minimum_absolute_delta: '0.15',
    maximum_absolute_delta: '0.3',
    minimum_annualized_return: '10',
  },
  ccFilters: {
    version: 1,
    minimum_dte: 7,
    maximum_dte: 45,
    minimum_absolute_delta: 0.15,
    maximum_absolute_delta: 0.3,
    minimum_annualized_return: 10,
  },
  ccFilterError: null,
  ccFilterSaveStatus: 'saved' as const,
  tickerSaveError: null,
  isTickerUpdatePending: false,
  scanActionError: null,
  activeJob: null,
  ccSnapshot: snapshot,
  ccSort: { key: 'annualized_return' as const, direction: 'desc' as const },
  addCspTickers: vi.fn(),
  removeCspTicker: vi.fn(),
  clearCspTickers: vi.fn(),
  updateCcFilterDraft: vi.fn(),
  resetCcFilters: vi.fn(),
  startCcScan: vi.fn(),
  cancelActiveScan: vi.fn(),
  setCcSort: vi.fn(),
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.clearAllMocks()
  Object.assign(state, {
    activeJob: null,
    ccSnapshot: snapshot,
    ccFilters: {
      version: 1,
      minimum_dte: 7,
      maximum_dte: 45,
      minimum_absolute_delta: 0.15,
      maximum_absolute_delta: 0.3,
      minimum_annualized_return: 10,
    },
  })
})

describe('CcScreenerPage', () => {
  it('uses the shared ticker list and independent CC controls and snapshot', () => {
    render(<CcScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByRole('heading', { name: 'Covered Call Screener' })).toBeTruthy()
    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(1)
    expect(screen.getByText('Gain %')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Minimum DTE'), {
      target: { value: '14' },
    })
    expect(state.updateCcFilterDraft).toHaveBeenCalledWith('minimum_dte', '14')

    fireEvent.click(screen.getByRole('button', { name: /scan 1 ticker/i }))
    expect(state.startCcScan).toHaveBeenCalled()
  })

  it('retains completed rows while a CC scan is active and supports cancellation', () => {
    Object.assign(state, {
      activeJob: {
        id: 'active-cc',
        screener: 'cc',
        status: 'active',
        tickers: ['AAPL', 'MSFT'],
        filters: state.ccFilters,
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

    render(<CcScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('Scan in progress')).toBeTruthy()
    expect(screen.getByText('1 of 2 tickers scanned')).toBeTruthy()
    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(1)
    fireEvent.click(screen.getByRole('button', { name: /cancel scan/i }))
    expect(state.cancelActiveScan).toHaveBeenCalled()
  })

  it('refreshes a CC row before opening a selected-account short-call ticket', async () => {
    vi.mocked(api.refreshOptionsScreenerQuote).mockResolvedValue({
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 110,
      right: 'CALL',
      contract: { con_id: 456, local_symbol: 'AAPL REFRESHED CALL' },
      bid: 1.1,
      ask: 1.3,
      midpoint: 1.2,
      delta: 0.2,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(
      <CcScreenerPage
        portfolio={portfolio}
        selectedAccount="DU222"
      />,
    )
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(await screen.findByText('Option strategy')).toBeTruthy()
    expect(api.refreshOptionsScreenerQuote).toHaveBeenCalledWith({
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 110,
      right: 'CALL',
      contract: candidate.contract,
    })
    expect(screen.getByText('Sell')).toBeTruthy()
    expect(
      (screen.getByLabelText('Quantity 110 CALL') as HTMLInputElement).value,
    ).toBe('-1')
    expect(
      (screen.getByLabelText('Net limit credit') as HTMLInputElement).value,
    ).toBe('1.20')
    expect(screen.queryByText('Select an account.')).toBeNull()
  })

  it('opens without holdings or an account and allows larger whole quantities', async () => {
    vi.mocked(api.refreshOptionsScreenerQuote).mockResolvedValue({
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 110,
      right: 'CALL',
      contract: { con_id: 456, local_symbol: 'AAPL REFRESHED CALL' },
      bid: 1.1,
      ask: 1.3,
      midpoint: 1.2,
      delta: 0.2,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(<CcScreenerPage portfolio={portfolio} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(await screen.findByText('Select an account.')).toBeTruthy()
    const quantity = screen.getByLabelText('Quantity 110 CALL')
    fireEvent.change(quantity, { target: { value: '-5' } })
    await waitFor(() =>
      expect((quantity as HTMLInputElement).value).toBe('-5'),
    )
    expect(screen.queryByText(/shares|position/i)).toBeNull()
  })

  it('does not open a stale ticket when call refresh fails', async () => {
    vi.mocked(api.refreshOptionsScreenerQuote).mockRejectedValue(
      new Error('The selected call contract can no longer be resolved.'),
    )

    render(<CcScreenerPage portfolio={null} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(
      await screen.findByText(
        'The selected call contract can no longer be resolved.',
      ),
    ).toBeTruthy()
    expect(screen.queryByText('Option strategy')).toBeNull()
  })

})
