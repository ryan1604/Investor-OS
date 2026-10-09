// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/optionsScreeners'
import { CspScreenerPage } from '@/features/options-screeners/CspScreenerPage'
import type { CashSecuredPutCandidate } from '@/api/optionsScreeners'

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
        csp: {
          tickers: state.cspTickers,
          filterDraft: state.cspFilterDraft,
          filters: state.cspFilters,
          filterError: state.cspFilterError,
          filterSaveStatus: state.cspFilterSaveStatus,
          snapshot: state.cspSnapshot,
          sort: state.cspSort,
          addTickers: state.addCspTickers,
          removeTicker: state.removeCspTicker,
          clearTickers: state.clearCspTickers,
          updateFilterDraft: state.updateCspFilterDraft,
          resetFilters: state.resetCspFilters,
          startScan: state.startCspScan,
          setSort: state.setCspSort,
          latestJob: state.latestCspJob,
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

const candidate: CashSecuredPutCandidate = {
  strategy: 'csp',
  ticker: 'AAPL',
  annualized_return: 20,
  stock_price: 110,
  strike: 100,
  expiration: '2026-07-17',
  dte: 32,
  delta: -0.2,
  bid: 1,
  ask: 1.2,
  discount_percentage: 9.09,
  contract: { con_id: 123, local_symbol: 'AAPL PUT' },
}

const completedSnapshot = {
  screener: 'csp' as const,
  job_id: 'job-1',
  total_match_count: 1,
  excluded_contracts: 0,
  candidates: [candidate],
  errors: ['SNAPSHOT: retained failure'],
  warnings: [],
  completed_at: '2026-06-15T00:00:00Z',
}

const state = {
  isLoading: false,
  loadError: null,
  cspTickers: ['AAPL'],
  cspFilterDraft: {
    minimumDte: '7',
    maximumDte: '45',
    minimumAbsoluteDelta: '0.1',
    maximumAbsoluteDelta: '0.3',
    minimumAnnualizedReturn: '10',
  },
  cspFilters: {
    version: 1,
    minimum_dte: 7,
    maximum_dte: 45,
    minimum_absolute_delta: 0.1,
    maximum_absolute_delta: 0.3,
    minimum_annualized_return: 10,
  },
  cspFilterError: null,
  cspFilterSaveStatus: 'saved' as const,
  tickerSaveError: null,
  isTickerUpdatePending: false,
  scanActionError: null,
  activeJob: null,
  latestCspJob: null,
  cspSnapshot: completedSnapshot,
  cspSort: { key: 'annualized_return' as const, direction: 'desc' as const },
  addCspTickers: vi.fn(),
  removeCspTicker: vi.fn(),
  clearCspTickers: vi.fn(),
  updateCspFilterDraft: vi.fn(),
  resetCspFilters: vi.fn(),
  startCspScan: vi.fn(),
  cancelActiveScan: vi.fn(),
  setCspSort: vi.fn(),
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.clearAllMocks()
  Object.assign(state, {
    activeJob: null,
    latestCspJob: null,
    cspSnapshot: completedSnapshot,
    scanActionError: null,
    cspFilters: {
      version: 1,
      minimum_dte: 7,
      maximum_dte: 45,
      minimum_absolute_delta: 0.1,
      maximum_absolute_delta: 0.3,
      minimum_annualized_return: 10,
    },
  })
})

describe('CspScreenerPage trade integration', () => {
  it('prompts for a scan before any completed snapshot exists', () => {
    Object.assign(state, { cspSnapshot: null })

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('Start a scan')).toBeTruthy()
    expect(screen.queryByText('No matching contracts')).toBeNull()
  })

  it('shows no matches after a completed scan returns no candidates', () => {
    Object.assign(state, {
      cspSnapshot: {
        ...completedSnapshot,
        total_match_count: 0,
        candidates: [],
      },
    })

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('No matching contracts')).toBeTruthy()
    expect(screen.queryByText('Start a scan')).toBeNull()
  })

  it('refreshes a completed result before opening a prefilled short-put ticket', async () => {
    vi.mocked(api.refreshOptionsScreenerQuote).mockResolvedValue({
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 100,
      right: 'PUT',
      contract: { con_id: 456, local_symbol: 'AAPL REFRESHED PUT' },
      bid: 1.1,
      ask: 1.3,
      midpoint: 1.2,
      delta: -0.2,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(await screen.findByText('Option strategy')).toBeTruthy()
    expect(api.refreshOptionsScreenerQuote).toHaveBeenCalledWith({
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 100,
      right: 'PUT',
      contract: candidate.contract,
    })
    expect(screen.getByText('Sell')).toBeTruthy()
    expect(
      (screen.getByLabelText('Quantity 100 PUT') as HTMLInputElement).value,
    ).toBe('-1')
    expect(
      (screen.getByLabelText('Net limit credit') as HTMLInputElement).value,
    ).toBe('1.20')
    expect(screen.getByText('Select an account.')).toBeTruthy()
  })

  it('does not open a stale ticket when refresh fails', async () => {
    vi.mocked(api.refreshOptionsScreenerQuote).mockRejectedValue(
      new Error('The selected option contract can no longer be resolved.'),
    )

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])

    expect(
      await screen.findByText(
        'The selected option contract can no longer be resolved.',
      ),
    ).toBeTruthy()
    expect(screen.queryByText('Option strategy')).toBeNull()
  })

  it('warns but still opens when refreshed values miss current filters', async () => {
    vi.mocked(api.refreshOptionsScreenerQuote).mockResolvedValue({
      ticker: 'AAPL',
      expiration: '2026-07-17',
      strike: 100,
      right: 'PUT',
      contract: { con_id: 456, local_symbol: 'AAPL REFRESHED PUT' },
      bid: 0.1,
      ask: 0.2,
      midpoint: 0.15,
      delta: -0.5,
      refreshed_at: '2026-06-15T00:00:00Z',
    })

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])

    await waitFor(() => {
      expect(
        screen.getByText(
          'The refreshed contract no longer satisfies the current CSP scan filters.',
        ),
      ).toBeTruthy()
    })
    expect(screen.getByText('Option strategy')).toBeTruthy()
  })

  it('uses strike-based CSP return at the refreshed filter boundary', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-06-15T12:00:00Z'))
    Object.assign(state, {
      cspFilters: {
        ...state.cspFilters,
        minimum_annualized_return: 12.2,
      },
    })
    vi.mocked(api.refreshOptionsScreenerQuote).mockResolvedValue({
      ticker: 'AAPL',
      expiration: '2026-07-15',
      strike: 100,
      right: 'PUT',
      contract: { con_id: 456, local_symbol: 'AAPL REFRESHED PUT' },
      bid: 0.9,
      ask: 1.1,
      midpoint: 1,
      delta: -0.2,
      refreshed_at: '2026-06-15T12:00:00Z',
    })

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)
    fireEvent.click(screen.getAllByRole('row')[1])
    await vi.runAllTimersAsync()

    expect(
      screen.getByText(
        'The refreshed contract no longer satisfies the current CSP scan filters.',
      ),
    ).toBeTruthy()
  })

  it('shows simplified progress, cancellation, and retained completed rows', async () => {
    Object.assign(state, {
      activeJob: {
        id: 'active-job',
        screener: 'csp',
        status: 'active',
        tickers: ['MSFT', 'NVDA'],
        filters: state.cspFilters,
        total_tickers: 2,
        completed_tickers: 1,
        progress_message: '1 of 2 tickers scanned',
        successful_tickers: 1,
        no_match_tickers: 0,
        failed_tickers: 1,
        total_match_count: 1,
        excluded_contracts: 3,
        candidates: [{ ...candidate, ticker: 'MSFT' }],
        errors: ['NVDA: market unavailable'],
        warnings: [
          {
            ticker: 'MSFT',
            category: 'excluded_contracts',
            message: 'Excluded invalid contracts.',
            count: 3,
          },
        ],
        started_at: '2026-06-15T00:00:00Z',
        finished_at: null,
        successful_completion_at: null,
      },
    })

    render(<CspScreenerPage portfolio={null} selectedAccount={null} />)

    expect(screen.getByText('Scan in progress')).toBeTruthy()
    expect(screen.getByText('1 of 2 tickers scanned')).toBeTruthy()
    expect(screen.queryByText('Live results (1)')).toBeNull()
    expect(screen.queryByText('MSFT')).toBeNull()
    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(1)
    expect(screen.queryByText(/NVDA: market unavailable/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /cancel scan/i }))
    expect(state.cancelActiveScan).toHaveBeenCalled()
  })
})
