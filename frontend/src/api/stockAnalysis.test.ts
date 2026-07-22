import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deleteStockAnalysisModel,
  fetchStockAnalysisCurrentPrice,
  fetchStockAnalysisModel,
  fetchStockAnalysisModels,
  refreshStockAnalysisCurrentPrices,
  upsertStockAnalysisModel,
  type StockAnalysisModelRequest,
} from '@/api/stockAnalysis'

const modelRequest: StockAnalysisModelRequest = {
  version: 1,
  payload: {
    bull: { revenue: [100] },
    base: {},
    bear: {},
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('stock analysis api', () => {
  it('fetches, refreshes, and upserts stock analysis models', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ ticker: 'AAPL' }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ticker: 'AAPL' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ticker: 'AAPL', current_price: 42.5 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            results: [
              {
                ticker: 'AAPL',
                status: 'refreshed',
                current_price: 42.5,
                message: null,
              },
            ],
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ticker: 'AAPL' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchStockAnalysisModels()
    await fetchStockAnalysisModel(' aapl ')
    await fetchStockAnalysisCurrentPrice('aapl')
    await refreshStockAnalysisCurrentPrices()
    await upsertStockAnalysisModel('aapl', modelRequest)
    await deleteStockAnalysisModel('aapl')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/stock-analysis',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/stock-analysis/AAPL',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/stock-analysis/AAPL/current-price',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      'http://127.0.0.1:8000/stock-analysis/current-prices/refresh',
      {
        method: 'POST',
        signal: undefined,
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      'http://127.0.0.1:8000/stock-analysis/AAPL',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(modelRequest),
        signal: undefined,
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      'http://127.0.0.1:8000/stock-analysis/AAPL',
      { method: 'DELETE', signal: undefined },
    )
  })

  it('surfaces backend stock analysis errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Ticker is required.' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(fetchStockAnalysisModel('AAPL')).rejects.toThrow(
      'Ticker is required.',
    )
  })
})
