// @vitest-environment jsdom

import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchStockAnalysisModels,
  refreshStockAnalysisCurrentPrices,
  type StockAnalysisJsonValue,
  type StockAnalysisModel,
  type StockAnalysisScenarioPayload,
} from '@/api/stockAnalysis'
import { RankStocksPage } from '@/features/rank-stocks/RankStocksPage'

vi.mock('@/api/stockAnalysis', () => ({
  fetchStockAnalysisModels: vi.fn(),
  refreshStockAnalysisCurrentPrices: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(refreshStockAnalysisCurrentPrices).mockResolvedValue({ results: [] })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('RankStocksPage', () => {
  it('renders all scenario and metric ranking tables from saved models', async () => {
    vi.mocked(fetchStockAnalysisModels).mockResolvedValue([
      savedModel('AAPL', 10, {
        bull: scenarioPayload({ priceToSales: [2, 2, 2, 2, 2] }),
        base: scenarioPayload({ priceToSales: [1, 1, 1, 1, 1] }),
        bear: scenarioPayload({ priceToSales: [0.5, 0.5, 0.5, 0.5, 0.5] }),
      }),
      savedModel('MSFT', 10, {
        bull: scenarioPayload({ priceToSales: [3, 3, 3, 3, 3] }),
        base: scenarioPayload({ priceToSales: [1.5, 1.5, 1.5, 1.5, 1.5] }),
        bear: scenarioPayload({}),
      }),
    ])

    render(<RankStocksPage />)

    expect(await screen.findByText('Rank Stocks')).toBeTruthy()
    expect(screen.getAllByText('P/S')).toHaveLength(3)
    expect(screen.getAllByText('P/E')).toHaveLength(3)
    expect(screen.getAllByText('P/EBITDA')).toHaveLength(3)
    expect(screen.getAllByText('P/OCF')).toHaveLength(3)
    expect(screen.getAllByText('P/FCF')).toHaveLength(3)

    const bullSection = screen.getByRole('heading', { name: 'Bull' })
      .parentElement?.parentElement
    expect(bullSection).not.toBeNull()
    const firstTable = within(bullSection as HTMLElement).getAllByRole('table')[0]
    const rows = within(firstTable).getAllByRole('row')

    expect(within(rows[1]).getByText('MSFT')).toBeTruthy()
    expect(within(rows[1]).getByText('+200.00%')).toBeTruthy()
    expect(within(rows[2]).getByText('AAPL')).toBeTruthy()
    expect(within(rows[2]).getByText('+100.00%')).toBeTruthy()
  })

  it('sorts missing rankings last and refreshes saved prices immediately', async () => {
    vi.mocked(fetchStockAnalysisModels).mockResolvedValue([
      savedModel('AAPL', 10, {
        bull: scenarioPayload({ priceToSales: [2, 2, 2, 2, 2] }),
      }),
      savedModel('NFLX', null, {
        bull: scenarioPayload({ priceToSales: [9, 9, 9, 9, 9] }),
      }),
    ])
    vi.mocked(refreshStockAnalysisCurrentPrices).mockResolvedValue({
      results: [
        {
          ticker: 'AAPL',
          status: 'refreshed',
          current_price: 20,
          message: null,
        },
        {
          ticker: 'NFLX',
          status: 'missing',
          current_price: null,
          message: 'No daily price data is available for NFLX.',
        },
      ],
    })

    render(<RankStocksPage />)

    await waitFor(() => {
      expect(refreshStockAnalysisCurrentPrices).toHaveBeenCalledTimes(1)
    })
    expect(await screen.findByText('Prices updated')).toBeTruthy()

    const bullSection = screen.getByRole('heading', { name: 'Bull' })
      .parentElement?.parentElement
    const firstTable = within(bullSection as HTMLElement).getAllByRole('table')[0]
    const rows = within(firstTable).getAllByRole('row')

    expect(within(rows[1]).getByText('AAPL')).toBeTruthy()
    expect(within(rows[1]).getByText('0.00%')).toBeTruthy()
    expect(within(rows[2]).getByText('NFLX')).toBeTruthy()
    expect(within(rows[2]).getByText('-')).toBeTruthy()
    expect(screen.getByText('1 missing price')).toBeTruthy()
  })

  it('omits deleted stock analysis tickers after saved models reload', async () => {
    vi.mocked(fetchStockAnalysisModels).mockResolvedValue([
      savedModel('MSFT', 10, {
        bull: scenarioPayload({ priceToSales: [3, 3, 3, 3, 3] }),
      }),
    ])

    render(<RankStocksPage />)

    expect((await screen.findAllByText('MSFT')).length).toBeGreaterThan(0)
    expect(screen.queryByText('AAPL')).toBeNull()
    expect(screen.getByText('1 tickers')).toBeTruthy()
  })

  it('refreshes every 15 minutes only while mounted', async () => {
    const intervalRefresh = deferred<{
      results: Awaited<
        ReturnType<typeof refreshStockAnalysisCurrentPrices>
      >['results']
    }>()
    const setIntervalSpy = vi
      .spyOn(window, 'setInterval')
      .mockImplementation(() => {
        return 1
      })
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')
    vi.mocked(fetchStockAnalysisModels).mockResolvedValue([
      savedModel('AAPL', 10, {
        bull: scenarioPayload({ priceToSales: [2, 2, 2, 2, 2] }),
      }),
    ])
    vi.mocked(refreshStockAnalysisCurrentPrices)
      .mockResolvedValueOnce({ results: [] })
      .mockReturnValueOnce(intervalRefresh.promise)

    const { unmount } = render(<RankStocksPage />)

    await waitFor(() => {
      expect(refreshStockAnalysisCurrentPrices).toHaveBeenCalledTimes(1)
    })
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 900000)

    const scheduledRefresh = setIntervalSpy.mock.calls[0][0]
    if (typeof scheduledRefresh === 'function') {
      act(() => {
        scheduledRefresh()
      })
    }

    await waitFor(() => {
      expect(refreshStockAnalysisCurrentPrices).toHaveBeenCalledTimes(2)
    })

    unmount()

    expect(clearIntervalSpy).toHaveBeenCalledWith(1)
    expect(
      vi.mocked(refreshStockAnalysisCurrentPrices).mock.calls[1][0]?.aborted,
    ).toBe(true)
  })

  it('invalidates a superseded refresh response', async () => {
    const setIntervalSpy = vi
      .spyOn(window, 'setInterval')
      .mockImplementation(() => 1)
    const firstRefresh = deferred<{
      results: Awaited<
        ReturnType<typeof refreshStockAnalysisCurrentPrices>
      >['results']
    }>()
    const secondRefresh = deferred<{
      results: Awaited<
        ReturnType<typeof refreshStockAnalysisCurrentPrices>
      >['results']
    }>()
    vi.mocked(fetchStockAnalysisModels).mockResolvedValue([
      savedModel('AAPL', 10, {
        bull: scenarioPayload({ priceToSales: [2, 2, 2, 2, 2] }),
      }),
    ])
    vi.mocked(refreshStockAnalysisCurrentPrices)
      .mockReturnValueOnce(firstRefresh.promise)
      .mockReturnValueOnce(secondRefresh.promise)

    render(<RankStocksPage />)

    await waitFor(() => {
      expect(refreshStockAnalysisCurrentPrices).toHaveBeenCalledTimes(1)
    })
    const scheduledRefresh = setIntervalSpy.mock.calls[0][0]
    act(() => {
      if (typeof scheduledRefresh === 'function') {
        scheduledRefresh()
      }
    })

    expect(
      vi.mocked(refreshStockAnalysisCurrentPrices).mock.calls[0][0]?.aborted,
    ).toBe(true)

    secondRefresh.resolve({
      results: [
        {
          ticker: 'AAPL',
          status: 'refreshed',
          current_price: 20,
          message: null,
        },
      ],
    })
    await screen.findByText('Prices updated')

    firstRefresh.resolve({
      results: [
        {
          ticker: 'AAPL',
          status: 'refreshed',
          current_price: 5,
          message: null,
        },
      ],
    })
    await act(async () => {
      await firstRefresh.promise
    })

    const bullSection = screen.getByRole('heading', { name: 'Bull' })
      .parentElement?.parentElement
    const firstTable = within(bullSection as HTMLElement).getAllByRole('table')[0]
    expect(within(firstTable).getByText('0.00%')).toBeTruthy()
    expect(within(firstTable).queryByText('+300.00%')).toBeNull()
  })

  it('clears a refresh error when a retry starts and succeeds', async () => {
    vi.mocked(fetchStockAnalysisModels).mockResolvedValue([
      savedModel('AAPL', 10, {
        bull: scenarioPayload({ priceToSales: [2, 2, 2, 2, 2] }),
      }),
    ])
    const retry = deferred<{
      results: Awaited<
        ReturnType<typeof refreshStockAnalysisCurrentPrices>
      >['results']
    }>()
    vi.mocked(refreshStockAnalysisCurrentPrices)
      .mockRejectedValueOnce(new Error('Refresh unavailable'))
      .mockReturnValueOnce(retry.promise)

    render(<RankStocksPage />)

    expect(await screen.findByText('Refresh unavailable')).toBeTruthy()
    act(() => {
      screen.getByRole('button', { name: 'Refresh' }).click()
    })
    expect(screen.queryByText('Refresh unavailable')).toBeNull()

    retry.resolve({ results: [] })
    expect(await screen.findByText('Prices updated')).toBeTruthy()
    expect(screen.queryByText('Refresh unavailable')).toBeNull()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })

  return { promise, reject, resolve }
}

function savedModel(
  ticker: string,
  currentPrice: number | null,
  payload: Partial<StockAnalysisModel['payload']>,
): StockAnalysisModel {
  return {
    ticker,
    version: 1,
    current_price: currentPrice,
    payload: {
      bull: {},
      base: {},
      bear: {},
      ...payload,
    },
    updated_at: '2026-06-06T00:00:00+00:00',
  }
}

function scenarioPayload(
  overrides: StockAnalysisScenarioPayload,
): StockAnalysisScenarioPayload {
  return {
    amountOfShares: yearValues(100, null, null, null, null),
    sharesChangePercent: yearValues(0, 0, 0, 0, 0),
    revenue: yearValues(1000, null, null, null, null),
    revenueGrowthPercent: yearValues(0, 0, 0, 0, 0),
    netIncome: yearValues(100, null, null, null, null),
    netIncomeGrowthPercent: yearValues(0, 0, 0, 0, 0),
    ebitda: yearValues(250, null, null, null, null),
    ebitdaGrowthPercent: yearValues(0, 0, 0, 0, 0),
    operatingCashFlow: yearValues(200, null, null, null, null),
    operatingCashFlowGrowthPercent: yearValues(0, 0, 0, 0, 0),
    freeCashFlow: yearValues(150, null, null, null, null),
    freeCashFlowGrowthPercent: yearValues(0, 0, 0, 0, 0),
    peEstimateLow: yearValues(10, 10, 10, 10, 10),
    priceToEbitda: yearValues(4, 4, 4, 4, 4),
    priceToOperatingCashFlow: yearValues(5, 5, 5, 5, 5),
    priceToFreeCashFlow: yearValues(8, 8, 8, 8, 8),
    ...overrides,
  }
}

function yearValues(
  first: StockAnalysisJsonValue,
  second: StockAnalysisJsonValue,
  third: StockAnalysisJsonValue,
  fourth: StockAnalysisJsonValue,
  fifth: StockAnalysisJsonValue,
) {
  return [first, second, third, fourth, fifth]
}
