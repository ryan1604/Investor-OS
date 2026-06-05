import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchStockAnalysisCurrentPrice,
  fetchStockAnalysisModel,
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
  it('fetches and upserts ticker models through normalized endpoints', async () => {
    const fetchMock = vi
      .fn()
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
        new Response(JSON.stringify({ ticker: 'AAPL' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchStockAnalysisModel(' aapl ')
    await fetchStockAnalysisCurrentPrice('aapl')
    await upsertStockAnalysisModel('aapl', modelRequest)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/stock-analysis/AAPL',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/stock-analysis/AAPL/current-price',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/stock-analysis/AAPL',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(modelRequest),
        signal: undefined,
      },
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
