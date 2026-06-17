// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  OptionsScreenersProvider,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'

const api = vi.hoisted(() => ({
  cancelOptionsScreenerScan: vi.fn(),
  fetchOptionsScreenerScanState: vi.fn(),
  fetchOptionsScreenerSettings: vi.fn(),
  getOptionsScreenerScansWsUrl: vi.fn(() => 'ws://screeners'),
  replaceOptionsScreenerTickerList: vi.fn(),
  saveOptionsScreenerFilters: vi.fn(),
  startOptionsScreenerScan: vi.fn(),
}))

vi.mock('@/api/optionsScreeners', () => api)

class FakeWebSocket {
  static sockets: FakeWebSocket[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }
  close() {}
  receive(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>)
  }
}

beforeEach(() => {
  FakeWebSocket.sockets = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  api.fetchOptionsScreenerSettings.mockResolvedValue({
    ticker_lists: { csp_cc: ['AAPL'], cs: [] },
    filters: {
      csp: filters(),
      cc: filters(),
      cs: { ...filters(), strategy_types: ['put_credit_spread'], spread_widths: [5] },
    },
  })
  api.fetchOptionsScreenerScanState.mockResolvedValue({
    active_job: null,
    latest_jobs: { csp: null, cc: null, cs: null },
    completed_snapshots: { csp: null, cc: null, cs: null },
  })
  api.saveOptionsScreenerFilters.mockImplementation(async (_screener, value) => value)
  api.replaceOptionsScreenerTickerList.mockImplementation(
    async (listName, tickers) => ({ list_name: listName, tickers }),
  )
  api.startOptionsScreenerScan.mockResolvedValue(job())
  api.cancelOptionsScreenerScan.mockResolvedValue(
    job({ status: 'cancelled' }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('OptionsScreenersProvider', () => {
  it('loads REST state before opening the WebSocket and merges live jobs', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )

    expect(screen.getByText('loading')).toBeTruthy()
    expect(FakeWebSocket.sockets).toHaveLength(0)
    await waitFor(() => expect(screen.getByText('AAPL')).toBeTruthy())
    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    FakeWebSocket.sockets[0].receive({
      type: 'job_started',
      job: job({ status: 'active', progress_message: '0 of 1 tickers scanned' }),
    })
    expect(await screen.findByText('0 of 1 tickers scanned')).toBeTruthy()
  })

  it('rolls back optimistic ticker changes when persistence fails', async () => {
    api.replaceOptionsScreenerTickerList.mockRejectedValueOnce(
      new Error('Save failed'),
    )
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    await screen.findByText('AAPL')

    fireEvent.click(screen.getByRole('button', { name: 'add ticker' }))
    await waitFor(() => expect(screen.getByText('Save failed')).toBeTruthy())
    expect(screen.getByText('AAPL').textContent).toBe('AAPL')
    expect(screen.queryByText('MSFT')).toBeNull()
  })

  it('updates the shared CSP and CC ticker list together', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    await screen.findByText('AAPL')

    fireEvent.click(screen.getByRole('button', { name: 'add ticker' }))

    await waitFor(() =>
      expect(screen.getByTestId('cc-tickers').textContent).toBe('CC:AAPL,MSFT'),
    )
    expect(api.replaceOptionsScreenerTickerList).toHaveBeenCalledWith(
      'csp_cc',
      ['AAPL', 'MSFT'],
    )
  })

  it('keeps CS tickers separate from the shared CSP and CC list', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    await screen.findByText('AAPL')

    fireEvent.click(screen.getByRole('button', { name: 'add cs ticker' }))

    await waitFor(() =>
      expect(screen.getByTestId('cs-tickers').textContent).toBe('CS:TSLA'),
    )
    expect(screen.getByTestId('cc-tickers').textContent).toBe('CC:AAPL')
    expect(api.replaceOptionsScreenerTickerList).toHaveBeenCalledWith(
      'cs',
      ['TSLA'],
    )
  })

  it('autosaves valid filter drafts and does not save invalid drafts', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    const input = await screen.findByLabelText('minimum dte')

    fireEvent.change(input, { target: { value: '10' } })
    await waitFor(() =>
      expect(api.saveOptionsScreenerFilters).toHaveBeenCalledWith(
        'csp',
        expect.objectContaining({ minimum_dte: 10 }),
      ),
    )

    api.saveOptionsScreenerFilters.mockClear()
    fireEvent.change(input, { target: { value: '50' } })
    await new Promise((resolve) => window.setTimeout(resolve, 400))
    expect(api.saveOptionsScreenerFilters).not.toHaveBeenCalled()
    expect(screen.getByText(/DTE must use whole days/)).toBeTruthy()
  })

  it('autosaves CC filters independently from CSP filters', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    const input = await screen.findByLabelText('cc minimum dte')

    fireEvent.change(input, { target: { value: '14' } })
    await waitFor(() =>
      expect(api.saveOptionsScreenerFilters).toHaveBeenCalledWith(
        'cc',
        expect.objectContaining({ minimum_dte: 14 }),
      ),
    )
    expect(api.saveOptionsScreenerFilters).not.toHaveBeenCalledWith(
      'csp',
      expect.objectContaining({ minimum_dte: 14 }),
    )
  })

  it('autosaves valid CS filters and keeps empty strategy selections local', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    const input = await screen.findByLabelText('cs minimum dte')

    fireEvent.change(input, { target: { value: '21' } })
    await waitFor(() =>
      expect(api.saveOptionsScreenerFilters).toHaveBeenCalledWith(
        'cs',
        expect.objectContaining({ minimum_dte: 21 }),
      ),
    )

    api.saveOptionsScreenerFilters.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'toggle put cs' }))
    await new Promise((resolve) => window.setTimeout(resolve, 400))
    expect(api.saveOptionsScreenerFilters).not.toHaveBeenCalled()
    expect(screen.getByText('Select at least one credit spread strategy.')).toBeTruthy()
  })

  it('ignores stale filter autosave responses that resolve after a newer save', async () => {
    const saves: {
      value: ReturnType<typeof filters>
      resolve: (value: ReturnType<typeof filters>) => void
    }[] = []
    api.saveOptionsScreenerFilters.mockImplementation(
      async (_screener, value) =>
        new Promise((resolve) => {
          saves.push({
            value,
            resolve: resolve as (value: ReturnType<typeof filters>) => void,
          })
        }),
    )
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    const input = await screen.findByLabelText('minimum dte')

    fireEvent.change(input, { target: { value: '10' } })
    await waitFor(() => expect(saves).toHaveLength(1))
    fireEvent.change(input, { target: { value: '11' } })
    await waitFor(() => expect(saves).toHaveLength(2))

    saves[1].resolve(saves[1].value)
    await waitFor(() => expect(screen.getByText('CSP minimum:11')).toBeTruthy())
    saves[0].resolve(saves[0].value)
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    expect(screen.getByText('CSP minimum:11')).toBeTruthy()
  })

  it('recovers active jobs and all completed screener snapshots from REST state', async () => {
    api.fetchOptionsScreenerScanState.mockResolvedValueOnce({
      active_job: job({ screener: 'cs', progress_message: '2 of 5 tickers scanned' }),
      latest_jobs: { csp: job(), cc: job({ screener: 'cc' }), cs: job({ screener: 'cs' }) },
      completed_snapshots: {
        csp: {
          screener: 'csp',
          job_id: 'previous-job',
          total_match_count: 1,
          excluded_contracts: 0,
          candidates: [candidate('MSFT')],
          errors: ['FAIL: retained failure'],
          warnings: [],
          completed_at: '2026-06-14T00:00:00Z',
        },
        cc: {
          screener: 'cc',
          job_id: 'cc-job',
          total_match_count: 1,
          excluded_contracts: 0,
          candidates: [ccCandidate('AAPL')],
          errors: [],
          warnings: [],
          completed_at: '2026-06-14T00:00:00Z',
        },
        cs: {
          screener: 'cs',
          job_id: 'cs-job',
          total_match_count: 1,
          excluded_contracts: 0,
          candidates: [csCandidate('TSLA')],
          errors: [],
          warnings: [],
          completed_at: '2026-06-14T00:00:00Z',
        },
      },
    })

    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )

    expect(await screen.findByText('2 of 5 tickers scanned')).toBeTruthy()
    expect(screen.getByText('MSFT')).toBeTruthy()
    expect(screen.getByText('CC snapshot:AAPL')).toBeTruthy()
    expect(screen.getByText('CS snapshot:TSLA')).toBeTruthy()
  })

  it('keeps scanner state while the page navigates away and back', async () => {
    render(
      <OptionsScreenersProvider>
        <NavigationHarness />
      </OptionsScreenersProvider>,
    )
    await screen.findByText('scanner page')
    await waitFor(() => expect(FakeWebSocket.sockets).toHaveLength(1))

    FakeWebSocket.sockets[0].receive({
      type: 'job_updated',
      job: job({
        candidates: [candidate('NVDA')],
        completed_tickers: 1,
        progress_message: '1 of 1 tickers scanned',
      }),
    })
    expect(await screen.findByText('NVDA')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'navigate' }))
    expect(screen.getByText('other page')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'navigate' }))

    expect(screen.getByText('NVDA')).toBeTruthy()
    expect(api.fetchOptionsScreenerSettings).toHaveBeenCalledTimes(1)
    expect(api.fetchOptionsScreenerScanState).toHaveBeenCalledTimes(1)
  })

  it('retains CC snapshots and sort state across navigation without refetching', async () => {
    api.fetchOptionsScreenerScanState.mockResolvedValueOnce({
      active_job: null,
      latest_jobs: { csp: null, cc: null, cs: null },
      completed_snapshots: {
        csp: null,
        cc: {
          screener: 'cc',
          job_id: 'cc-job',
          total_match_count: 1,
          excluded_contracts: 0,
          candidates: [ccCandidate('MSFT')],
          errors: [],
          warnings: [],
          completed_at: '2026-06-15T00:00:00Z',
        },
        cs: null,
      },
    })
    render(
      <OptionsScreenersProvider>
        <NavigationHarness />
      </OptionsScreenersProvider>,
    )

    expect(await screen.findByText('CC snapshot:MSFT')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'sort cc gain' }))
    expect(screen.getByText('CC sort:gain_percentage:desc')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'navigate' }))
    fireEvent.click(screen.getByRole('button', { name: 'navigate' }))

    expect(screen.getByText('CC snapshot:MSFT')).toBeTruthy()
    expect(screen.getByText('CC sort:gain_percentage:desc')).toBeTruthy()
    expect(api.fetchOptionsScreenerSettings).toHaveBeenCalledTimes(1)
    expect(api.fetchOptionsScreenerScanState).toHaveBeenCalledTimes(1)
    expect(api.startOptionsScreenerScan).not.toHaveBeenCalled()
  })

  it('retains CS snapshots and sort state across navigation without refetching', async () => {
    api.fetchOptionsScreenerScanState.mockResolvedValueOnce({
      active_job: null,
      latest_jobs: { csp: null, cc: null, cs: null },
      completed_snapshots: {
        csp: null,
        cc: null,
        cs: {
          screener: 'cs',
          job_id: 'cs-job',
          total_match_count: 1,
          excluded_contracts: 0,
          candidates: [csCandidate('TSLA')],
          errors: [],
          warnings: [],
          completed_at: '2026-06-15T00:00:00Z',
        },
      },
    })
    render(
      <OptionsScreenersProvider>
        <NavigationHarness />
      </OptionsScreenersProvider>,
    )

    expect(await screen.findByText('CS snapshot:TSLA')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'sort cs strategy' }))
    expect(screen.getByText('CS sort:strategy:desc')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'navigate' }))
    fireEvent.click(screen.getByRole('button', { name: 'navigate' }))

    expect(screen.getByText('CS snapshot:TSLA')).toBeTruthy()
    expect(screen.getByText('CS sort:strategy:desc')).toBeTruthy()
    expect(api.fetchOptionsScreenerSettings).toHaveBeenCalledTimes(1)
    expect(api.fetchOptionsScreenerScanState).toHaveBeenCalledTimes(1)
    expect(api.startOptionsScreenerScan).not.toHaveBeenCalled()
  })

  it('starts and cancels scans through the recovered active job', async () => {
    render(
      <OptionsScreenersProvider>
        <Harness />
      </OptionsScreenersProvider>,
    )
    await screen.findByText('AAPL')

    fireEvent.click(screen.getByRole('button', { name: 'start scan' }))
    await waitFor(() =>
      expect(api.startOptionsScreenerScan).toHaveBeenCalledWith('csp'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'cancel scan' }))
    await waitFor(() =>
      expect(api.cancelOptionsScreenerScan).toHaveBeenCalledWith('job-1'),
    )
  })
})

function Harness() {
  const state = useOptionsScreeners()
  if (state.isLoading) {
    return <span>loading</span>
  }
  return (
    <div>
      <span>{state.cspTickers.join(',')}</span>
      <span data-testid="cc-tickers">CC:{state.cspTickers.join(',')}</span>
      <span data-testid="cs-tickers">CS:{state.csTickers.join(',')}</span>
      <span>{state.tickerSaveError}</span>
      <span>{state.activeJob?.progress_message}</span>
      <span>
        {state.cspSnapshot?.candidates.map((item) => item.ticker).join(',')}
      </span>
      <span>{state.activeJob?.candidates.map((item) => item.ticker).join(',')}</span>
      <span>{state.cspFilterError}</span>
      <span>CSP minimum:{state.cspFilters.minimum_dte}</span>
      <span>{state.ccFilterError}</span>
      <span>{state.csFilterError}</span>
      <span>
        CC snapshot:
        {state.ccSnapshot?.candidates.map((item) => item.ticker).join(',')}
      </span>
      <span>CC sort:{state.ccSort.key}:{state.ccSort.direction}</span>
      <span>
        CS snapshot:
        {state.csSnapshot?.candidates.map((item) => item.ticker).join(',')}
      </span>
      <span>CS sort:{state.csSort.key}:{state.csSort.direction}</span>
      <label>
        minimum dte
        <input
          aria-label="minimum dte"
          value={state.cspFilterDraft.minimum_dte}
          onChange={(event) =>
            state.updateCspFilterDraft('minimum_dte', event.target.value)
          }
        />
      </label>
      <label>
        cc minimum dte
        <input
          aria-label="cc minimum dte"
          value={state.ccFilterDraft.minimum_dte}
          onChange={(event) =>
            state.updateCcFilterDraft('minimum_dte', event.target.value)
          }
        />
      </label>
      <label>
        cs minimum dte
        <input
          aria-label="cs minimum dte"
          value={state.csFilterDraft.minimum_dte}
          onChange={(event) =>
            state.updateCsFilterDraft('minimum_dte', event.target.value)
          }
        />
      </label>
      <button type="button" onClick={() => void state.addCspTickers(['MSFT'])}>
        add ticker
      </button>
      <button type="button" onClick={() => void state.addCsTickers(['TSLA'])}>
        add cs ticker
      </button>
      <button type="button" onClick={() => void state.startCspScan()}>
        start scan
      </button>
      <button
        type="button"
        onClick={() => state.toggleCsStrategyType('put_credit_spread')}
      >
        toggle put cs
      </button>
      <button type="button" onClick={() => state.setCcSort('gain_percentage')}>
        sort cc gain
      </button>
      <button type="button" onClick={() => state.setCsSort('strategy')}>
        sort cs strategy
      </button>
      <button type="button" onClick={() => void state.cancelActiveScan()}>
        cancel scan
      </button>
    </div>
  )
}

function NavigationHarness() {
  const [showScanner, setShowScanner] = useState(true)
  return (
    <div>
      <button type="button" onClick={() => setShowScanner((current) => !current)}>
        navigate
      </button>
      {showScanner ? (
        <>
          <span>scanner page</span>
          <Harness />
        </>
      ) : (
        <span>other page</span>
      )}
    </div>
  )
}

function filters() {
  return {
    version: 1,
    minimum_dte: 7,
    maximum_dte: 45,
    minimum_absolute_delta: 0.15,
    maximum_absolute_delta: 0.3,
    minimum_annualized_return: 10,
  }
}

function job(overrides = {}) {
  return {
    id: 'job-1',
    screener: 'csp',
    status: 'active',
    tickers: ['AAPL'],
    filters: filters(),
    total_tickers: 1,
    completed_tickers: 0,
    progress_message: '',
    successful_tickers: 0,
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
    ...overrides,
  }
}

function candidate(ticker: string) {
  return {
    strategy: 'csp',
    ticker,
    annualized_return: 20,
    stock_price: 110,
    strike: 100,
    expiration: '2026-07-17',
    dte: 30,
    delta: -0.2,
    bid: 1,
    ask: 1.2,
    discount_percentage: 9.09,
    contract: { con_id: 123, local_symbol: `${ticker} PUT` },
  }
}

function ccCandidate(ticker: string) {
  return {
    strategy: 'cc',
    ticker,
    annualized_return: 20,
    stock_price: 100,
    strike: 110,
    expiration: '2026-07-17',
    dte: 30,
    delta: 0.2,
    bid: 1,
    ask: 1.2,
    gain_percentage: 10,
    contract: { con_id: 456, local_symbol: `${ticker} CALL` },
  }
}

function csCandidate(ticker: string) {
  return {
    strategy: 'put_credit_spread',
    ticker,
    annualized_return: 20,
    stock_price: 100,
    short_strike: 95,
    long_strike: 90,
    expiration: '2026-07-17',
    dte: 30,
    short_delta: -0.2,
    net_bid: 1,
    net_ask: 1.2,
    distance_percentage: 5,
    short_contract: { con_id: 789, local_symbol: `${ticker} SHORT PUT` },
    long_contract: { con_id: 790, local_symbol: `${ticker} LONG PUT` },
  }
}
