// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchStockAnalysisCurrentPrice,
  fetchStockAnalysisModel,
  upsertStockAnalysisModel,
} from '@/api/stockAnalysis'
import { StockAnalysisPage } from '@/features/stock-analysis/StockAnalysisPage'

vi.mock('@/api/stockAnalysis', () => ({
  fetchStockAnalysisCurrentPrice: vi.fn(),
  fetchStockAnalysisModel: vi.fn(),
  upsertStockAnalysisModel: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(fetchStockAnalysisCurrentPrice).mockImplementation((ticker: string) =>
    Promise.resolve({
      ticker: ticker.trim().toUpperCase(),
      current_price: 10,
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('StockAnalysisPage', () => {
  it('opens a first-time model with normalized ticker text', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('MSFT'))

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: ' msft ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(await screen.findByText('MSFT valuation model')).toBeTruthy()
    expect(screen.getByText('Bull case')).toBeTruthy()
    expect(screen.getByText('Base case')).toBeTruthy()
    expect(screen.getByText('Bear case')).toBeTruthy()
    expect(
      (
        screen.getByLabelText(
          'Bull case Revenue Year 1',
        ) as HTMLInputElement
      ).value,
    ).toBe('')
  })

  it('aborts in-flight ticker loads on unmount', async () => {
    const modelSignals: AbortSignal[] = []
    const priceSignals: AbortSignal[] = []
    vi.mocked(fetchStockAnalysisModel).mockImplementation((_ticker, signal) => {
      if (signal) {
        modelSignals.push(signal)
      }

      return new Promise<never>(() => undefined)
    })
    vi.mocked(fetchStockAnalysisCurrentPrice).mockImplementation(
      (_ticker, signal) => {
        if (signal) {
          priceSignals.push(signal)
        }

        return new Promise<never>(() => undefined)
      },
    )

    const { unmount } = render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'AAPL' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))

    await waitFor(() => {
      expect(modelSignals).toHaveLength(1)
      expect(priceSignals).toHaveLength(1)
    })

    unmount()

    expect(modelSignals[0].aborted).toBe(true)
    expect(priceSignals[0].aborted).toBe(true)
  })

  it('uses placeholder year headers until the first forecast year is entered', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('AAPL'))

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'AAPL' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))

    const bullSection = (await screen.findByText('Bull case')).closest('section')
    expect(bullSection).not.toBeNull()
    expect(within(bullSection as HTMLElement).getByText('Year 1')).toBeTruthy()
    expect(within(bullSection as HTMLElement).getByText('Year 5')).toBeTruthy()

    const forecastYearInput = screen.getByLabelText(
      'First forecast year',
    ) as HTMLInputElement

    fireEvent.change(forecastYearInput, { target: { value: '20' } })

    expect(forecastYearInput.value).toBe('20')
    expect(within(bullSection as HTMLElement).getByText('Year 1')).toBeTruthy()

    fireEvent.change(forecastYearInput, { target: { value: '2027' } })

    expect(within(bullSection as HTMLElement).getByText('2027')).toBeTruthy()
    expect(within(bullSection as HTMLElement).getByText('2031')).toBeTruthy()
  })

  it('renders derived cells immediately from editable inputs', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('NVDA'))

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'NVDA' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('NVDA valuation model')

    const sharesInput = screen.getByLabelText('Base case Amount of shares Year 1')
    const revenueInput = screen.getByLabelText('Base case Revenue Year 1')
    const priceToSalesInput = screen.getByLabelText('Base case P/S Year 1')

    fireEvent.focus(sharesInput)
    fireEvent.change(sharesInput, {
      target: { value: '100' },
    })
    fireEvent.blur(sharesInput)
    fireEvent.focus(revenueInput)
    fireEvent.change(revenueInput, {
      target: { value: '1000' },
    })
    fireEvent.blur(revenueInput)
    fireEvent.focus(priceToSalesInput)
    fireEvent.change(priceToSalesInput, {
      target: { value: '2' },
    })
    fireEvent.blur(priceToSalesInput)

    expect(screen.getAllByText('$20.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
  })

  it('renders EBITDA rows and compact valuation metric labels', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('ADBE'))

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'ADBE' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('ADBE valuation model')

    expect(screen.getAllByText('EBITDA').length).toBeGreaterThan(0)
    expect(screen.getAllByText('EBITDA margin').length).toBeGreaterThan(0)
    expect(screen.getAllByText('EBITDA growth').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P/EBITDA').length).toBeGreaterThan(0)
    expect(screen.getAllByText('OCF').length).toBeGreaterThan(0)
    expect(screen.getAllByText('FCF').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P/S').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P/E').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P/OCF').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P/FCF').length).toBeGreaterThan(0)
    expect(
      screen.getAllByText('Share price based on P/E').length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByText('Share price based on P/EBITDA').length,
    ).toBeGreaterThan(0)
    expect(screen.queryByText('PE estimate high')).toBeNull()
    expect(screen.queryByText('Share price based on PE estimate high')).toBeNull()
    expect(screen.getByLabelText('Bull case EBITDA Year 1')).toBeTruthy()
    expect(screen.getByLabelText('Bull case P/EBITDA Year 1')).toBeTruthy()
  })

  it('formats shares, dollars, percentages, and EPS for display', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('HIMS'))

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'HIMS' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('HIMS valuation model')

    const sharesInput = screen.getByLabelText(
      'Bull case Amount of shares Year 1',
    ) as HTMLInputElement
    const revenueInput = screen.getByLabelText(
      'Bull case Revenue Year 1',
    ) as HTMLInputElement
    const revenueGrowthInput = screen.getByLabelText(
      'Bull case Revenue growth Year 1',
    ) as HTMLInputElement
    const netIncomeInput = screen.getByLabelText(
      'Bull case Net income Year 1',
    ) as HTMLInputElement

    fireEvent.focus(sharesInput)
    fireEvent.change(sharesInput, {
      target: { value: '1000000' },
    })
    expect(sharesInput.value).toBe('1000000')
    fireEvent.blur(sharesInput)

    fireEvent.focus(revenueInput)
    fireEvent.change(revenueInput, {
      target: { value: '1000000' },
    })
    fireEvent.blur(revenueInput)

    fireEvent.focus(revenueGrowthInput)
    fireEvent.change(revenueGrowthInput, {
      target: { value: '32' },
    })
    fireEvent.blur(revenueGrowthInput)

    fireEvent.focus(netIncomeInput)
    fireEvent.change(netIncomeInput, {
      target: { value: '333333.333' },
    })
    fireEvent.blur(netIncomeInput)

    expect(sharesInput.value).toBe('1,000,000')
    expect(revenueInput.value).toBe('$1,000,000.00')
    expect(revenueGrowthInput.value).toBe('32.00%')
    expect(screen.getAllByText('33.33%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('0.33').length).toBeGreaterThan(0)
  })

  it('renders current price, CAGR rows, and year five multiplier values', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue({
      ticker: 'ABCD',
      version: 1,
      current_price: null,
      payload: {
        bull: {},
        base: {
          amountOfShares: [100, null, null, null, null],
          sharesChangePercent: [0, 0, 0, 0, 0],
          revenue: [1000, null, null, null, null],
          revenueGrowthPercent: [0, 0, 0, 0, 0],
          priceToSales: [2, 2, 2, 2, 2],
        },
        bear: {},
      },
      updated_at: '2026-06-04T00:00:00+00:00',
    })
    vi.mocked(fetchStockAnalysisCurrentPrice).mockResolvedValue({
      ticker: 'ABCD',
      current_price: 10,
    })

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'ABCD' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(await screen.findByText('ABCD valuation model')).toBeTruthy()
    expect(screen.getByLabelText('Current price').textContent).toBe('$10.00')
    expect(screen.getAllByRole('columnheader', { name: 'Multiplier' })).toHaveLength(
      3,
    )
    expect(screen.getAllByText('100.00%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('25.99%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('18.92%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('14.87%').length).toBeGreaterThan(0)
  })

  it('saves IB current price beside the valuation payload', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('RBLX'))
    vi.mocked(upsertStockAnalysisModel).mockResolvedValue({
      ...emptyResponse('RBLX'),
      updated_at: '2026-06-04T00:00:00+00:00',
    })

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'RBLX' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('RBLX valuation model')

    fireEvent.change(screen.getByLabelText('First forecast year'), {
      target: { value: '2028' },
    })

    await waitFor(() => {
      expect(upsertStockAnalysisModel).toHaveBeenCalledWith('RBLX', {
        version: 1,
        payload: expect.not.objectContaining({
          currentPrice: expect.any(Number),
        }),
      }, expect.any(AbortSignal))
    }, { timeout: 1500 })
  })

  it('uses the saved current price snapshot when live price is unavailable', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue({
      ...emptyResponse('NFLX'),
      current_price: 25,
      updated_at: '2026-06-04T00:00:00+00:00',
    })
    vi.mocked(fetchStockAnalysisCurrentPrice).mockRejectedValue(
      new Error('Current price is unavailable for NFLX.'),
    )

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'NFLX' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(await screen.findByText('NFLX valuation model')).toBeTruthy()
    expect(screen.getByLabelText('Current price').textContent).toBe('$25.00')
  })

  it('discards an active cell edit when Escape is pressed', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('SHOP'))

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'SHOP' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('SHOP valuation model')

    const revenueInput = screen.getByLabelText(
      'Bull case Revenue Year 1',
    ) as HTMLInputElement

    fireEvent.focus(revenueInput)
    fireEvent.change(revenueInput, { target: { value: '1234' } })
    fireEvent.keyDown(revenueInput, { key: 'Escape' })

    expect(revenueInput.value).toBe('')
    expect(upsertStockAnalysisModel).not.toHaveBeenCalled()
  })

  it('autosaves edited valuation inputs after a debounce', async () => {
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('TSLA'))
    vi.mocked(upsertStockAnalysisModel).mockResolvedValue({
      ...emptyResponse('TSLA'),
      updated_at: '2026-06-04T00:00:00+00:00',
    })

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'TSLA' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('TSLA valuation model')

    fireEvent.change(screen.getByLabelText('First forecast year'), {
      target: { value: '2028' },
    })
    const revenueInput = screen.getByLabelText('Bull case Revenue 2028')
    fireEvent.focus(revenueInput)
    fireEvent.change(revenueInput, {
      target: { value: '500' },
    })
    fireEvent.blur(revenueInput)

    await waitFor(() => {
      expect(upsertStockAnalysisModel).toHaveBeenCalledWith('TSLA', {
        version: 1,
        payload: expect.objectContaining({
          firstForecastYear: 2028,
          bull: expect.objectContaining({
            revenue: [500, null, null, null, null],
          }),
        }),
      }, expect.any(AbortSignal))
    }, { timeout: 1500 })
    expect(await screen.findByText('Saved')).toBeTruthy()
  })

  it('aborts an in-flight autosave when a newer edit supersedes it', async () => {
    const saveSignals: AbortSignal[] = []
    vi.mocked(fetchStockAnalysisModel).mockResolvedValue(emptyResponse('META'))
    vi.mocked(upsertStockAnalysisModel).mockImplementation(
      (_ticker, _request, signal) => {
        if (signal) {
          saveSignals.push(signal)
        }

        return new Promise<never>(() => undefined)
      },
    )

    render(<StockAnalysisPage />)

    fireEvent.change(screen.getByLabelText('Ticker'), {
      target: { value: 'META' },
    })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText('META valuation model')

    fireEvent.change(screen.getByLabelText('First forecast year'), {
      target: { value: '2028' },
    })

    await waitFor(() => {
      expect(saveSignals).toHaveLength(1)
    }, { timeout: 1500 })

    fireEvent.change(screen.getByLabelText('First forecast year'), {
      target: { value: '2029' },
    })

    await waitFor(() => {
      expect(saveSignals[0].aborted).toBe(true)
    }, { timeout: 1500 })
  })
})

function emptyResponse(ticker: string) {
  return {
    ticker,
    version: 1,
    current_price: null,
    payload: {
      bull: {},
      base: {},
      bear: {},
    },
    updated_at: null,
  }
}
