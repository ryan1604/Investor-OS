import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createOptionsTradeTracker,
  deleteOptionsTradeTracker,
  fetchOptionsTradeStrategyOptions,
  fetchOptionsTradeTracker,
  fetchOptionsTradeTrackers,
  renameOptionsTradeTracker,
  replaceOptionsTradeStrategyOptions,
  replaceOptionsTradeTrackerTrades,
  updateOptionsTradeTrackerNotes,
} from '@/api/optionsTradeTrackers'

const trackerDetail = {
  tracker: {
    id: 'tracker 1',
    name: 'Income',
    created_at: '2026-06-06T01:02:03+00:00',
    updated_at: '2026-06-06T01:02:03+00:00',
  },
  trades: [],
  notes: '',
  strategy_options: [],
}

const tradesRequest = {
  trades: [
    {
      id: 'row-1',
      display_order: 1,
      status: 'Completed',
      strategy: 'Wheel',
      ticker: 'AAPL',
      month: 'jan',
      size: -1,
      strike_price: 190,
      credit_debit: 1.2,
      exit: null,
    },
  ],
} satisfies Parameters<typeof replaceOptionsTradeTrackerTrades>[1]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('options trade trackers api', () => {
  it('rejects blank tracker ids before sending a request', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchOptionsTradeTracker(' ')).rejects.toThrow(
      'Tracker id is required.',
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('covers tracker list, create, detail, rename, delete, trade, notes, and strategies', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ trackers: [trackerDetail.tracker] }),
      )
      .mockResolvedValueOnce(jsonResponse(trackerDetail))
      .mockResolvedValueOnce(jsonResponse(trackerDetail))
      .mockResolvedValueOnce(
        jsonResponse({
          ...trackerDetail,
          tracker: { ...trackerDetail.tracker, name: 'Growth' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse(trackerDetail))
      .mockResolvedValueOnce(
        jsonResponse({ ...trackerDetail, notes: 'Trade notes' }),
      )
      .mockResolvedValueOnce(jsonResponse({ strategies: ['Wheel'] }))
      .mockResolvedValueOnce(
        jsonResponse({ strategies: ['Wheel', 'Iron Condor'] }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchOptionsTradeTrackers()
    await createOptionsTradeTracker({ name: 'Income' })
    await fetchOptionsTradeTracker('tracker 1')
    await renameOptionsTradeTracker('tracker 1', { name: 'Growth' })
    await deleteOptionsTradeTracker('tracker 1')
    await replaceOptionsTradeTrackerTrades('tracker 1', tradesRequest)
    await updateOptionsTradeTrackerNotes('tracker 1', { notes: 'Trade notes' })
    await fetchOptionsTradeStrategyOptions()
    await replaceOptionsTradeStrategyOptions({
      strategies: ['Wheel', 'Iron Condor'],
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/options-trade-trackers',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/options-trade-trackers',
      jsonOptions('POST', { name: 'Income' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/options-trade-trackers/tracker%201',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      'http://127.0.0.1:8000/options-trade-trackers/tracker%201',
      jsonOptions('PATCH', { name: 'Growth' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      'http://127.0.0.1:8000/options-trade-trackers/tracker%201',
      { method: 'DELETE', signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      'http://127.0.0.1:8000/options-trade-trackers/tracker%201/trades',
      jsonOptions('PUT', tradesRequest),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      'http://127.0.0.1:8000/options-trade-trackers/tracker%201/notes',
      jsonOptions('PUT', { notes: 'Trade notes' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      8,
      'http://127.0.0.1:8000/options-trade-trackers/strategy-options',
      { signal: undefined },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      9,
      'http://127.0.0.1:8000/options-trade-trackers/strategy-options',
      jsonOptions('PUT', { strategies: ['Wheel', 'Iron Condor'] }),
    )
  })

  it('surfaces backend options tracker errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: 'Tracker name already exists.' }, 409),
      ),
    )

    await expect(createOptionsTradeTracker({ name: 'Income' })).rejects.toThrow(
      'Tracker name already exists.',
    )
  })
})

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function jsonOptions(method: 'PATCH' | 'POST' | 'PUT', payload: unknown) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: undefined,
  }
}
