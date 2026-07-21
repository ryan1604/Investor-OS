// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { EarningsWatchResponse, EarningsWatchRow } from '@/api/earningsWatch'
import { EarningsWatchPage } from '@/features/earnings-watch/EarningsWatchPage'

const api = vi.hoisted(() => ({
  addEarningsWatchTickers: vi.fn(),
  clearEarningsWatchReviews: vi.fn(),
  fetchEarningsWatch: vi.fn(),
  removeEarningsWatchTicker: vi.fn(),
  setEarningsWatchReviewed: vi.fn(),
}))

vi.mock('@/api/earningsWatch', () => api)

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchEarningsWatch.mockResolvedValue(response([]))
})

describe('EarningsWatchPage', () => {
  it('renders the empty page without a table', async () => {
    render(<EarningsWatchPage />)

    expect(await screen.findByRole('heading', { name: 'Earnings Watch' })).toBeTruthy()
    expect(screen.getByLabelText('Tickers')).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('adds pasted tickers, renders chips, rejected tokens, and the four-column table', async () => {
    const rows = [
      row('MSFT', '2026-06-24', 'upcoming'),
      row('AAPL', null, 'no_date'),
    ]
    api.addEarningsWatchTickers.mockResolvedValue({
      added: ['MSFT', 'AAPL'],
      existing: [],
      rejected: ['bad/ticker'],
      rows,
    })
    render(<EarningsWatchPage />)

    fireEvent.change(await screen.findByLabelText('Tickers'), {
      target: { value: 'msft, bad/ticker\naapl' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByText('Rejected: bad/ticker')).toBeTruthy()
    expect(screen.getByLabelText('Remove MSFT')).toBeTruthy()
    expect(screen.getByLabelText('Remove AAPL')).toBeTruthy()
    expect(screen.getByText('June 24, 2026')).toBeTruthy()
    expect(screen.getByText('-')).toBeTruthy()
    expect(tableHeaders()).toEqual(['Ticker', 'Earnings date', 'Status', 'Reviewed'])
  })

  it('keeps focus in the ticker input after enter submits', async () => {
    api.addEarningsWatchTickers.mockResolvedValue({
      added: ['AAPL'],
      existing: [],
      rejected: [],
      rows: [row('AAPL', '2026-07-30', 'upcoming')],
    })
    render(<EarningsWatchPage />)

    const input = await screen.findByLabelText('Tickers')
    input.focus()
    fireEvent.change(input, { target: { value: 'aapl' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(document.activeElement).toBe(input))
  })

  it('sorts rows by date while keeping no-date rows last', async () => {
    api.fetchEarningsWatch.mockResolvedValue(
      response([
        row('ZZZ', null, 'no_date'),
        row('MSFT', '2026-08-01', 'upcoming'),
        row('AAPL', '2026-07-30', 'last_known'),
      ]),
    )
    render(<EarningsWatchPage />)

    await screen.findAllByText('ZZZ')
    fireEvent.click(screen.getByRole('button', { name: /Earnings date/ }))
    expect(tickerCells()).toEqual(['AAPL', 'MSFT', 'ZZZ'])

    fireEvent.click(screen.getByRole('button', { name: /Earnings date/ }))
    expect(tickerCells()).toEqual(['MSFT', 'AAPL', 'ZZZ'])
  })

  it('rolls back an optimistic checkbox change when persistence fails', async () => {
    api.fetchEarningsWatch.mockResolvedValue(
      response([row('AAPL', '2026-07-30', 'upcoming', false)]),
    )
    api.setEarningsWatchReviewed.mockRejectedValue(new Error('Review update failed.'))
    render(<EarningsWatchPage />)

    const checkbox = await screen.findByLabelText('Reviewed AAPL')
    fireEvent.click(checkbox)

    await waitFor(() =>
      expect(screen.getByText('Review update failed.')).toBeTruthy(),
    )
    expect(checkbox.getAttribute('aria-checked')).toBe('false')
  })

  it('lets backend reviewed changes win when no local edit is pending', async () => {
    vi.useFakeTimers()
    api.fetchEarningsWatch
      .mockResolvedValueOnce(
        response([row('AAPL', '2026-07-30', 'upcoming', false)], {
          state: 'refreshing',
        }),
      )
      .mockResolvedValueOnce(
        response([row('AAPL', '2026-07-30', 'upcoming', true)]),
      )
    render(<EarningsWatchPage />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByLabelText('Reviewed AAPL').getAttribute('aria-checked')).toBe(
      'false',
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByLabelText('Reviewed AAPL').getAttribute('aria-checked')).toBe(
      'true',
    )
  })

  it('keeps pending local reviewed edits optimistic during polling', async () => {
    vi.useFakeTimers()
    const reviewUpdate = deferred<EarningsWatchRow>()
    api.fetchEarningsWatch
      .mockResolvedValueOnce(
        response([row('AAPL', '2026-07-30', 'upcoming', false)], {
          state: 'refreshing',
        }),
      )
      .mockResolvedValueOnce(
        response([row('AAPL', '2026-07-30', 'upcoming', false)], {
          state: 'succeeded',
        }),
      )
    api.setEarningsWatchReviewed.mockReturnValue(reviewUpdate.promise)
    render(<EarningsWatchPage />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    const checkbox = screen.getByLabelText('Reviewed AAPL')
    fireEvent.click(checkbox)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(checkbox.getAttribute('aria-checked')).toBe('true')

    await act(async () => {
      reviewUpdate.resolve(row('AAPL', '2026-07-30', 'upcoming', true))
      await reviewUpdate.promise
    })
    expect(checkbox.getAttribute('aria-checked')).toBe('true')
  })

  it('removes tickers only through chips and clears reviewed rows', async () => {
    const rows = [
      row('AAPL', '2026-07-30', 'upcoming', true),
      row('MSFT', '2026-08-01', 'upcoming', true),
    ]
    api.fetchEarningsWatch.mockResolvedValue(response(rows))
    api.removeEarningsWatchTicker.mockResolvedValue(rows[0])
    api.clearEarningsWatchReviews.mockResolvedValue({
      rows: [{ ...rows[1], reviewed: false }],
    })
    render(<EarningsWatchPage />)

    fireEvent.click(await screen.findByLabelText('Remove AAPL'))
    await waitFor(() => expect(api.removeEarningsWatchTicker).toHaveBeenCalledWith('AAPL'))
    expect(screen.queryByText('AAPL')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Clear all reviewed' }))
    await waitFor(() =>
      expect(screen.getByLabelText('Reviewed MSFT').getAttribute('aria-checked')).toBe(
        'false',
      ),
    )
  })

  it('polls while refreshing, keeps rows during warnings, and stops after unmount', async () => {
    vi.useFakeTimers()
    api.fetchEarningsWatch
      .mockResolvedValueOnce(
        response([row('AAPL', '2026-07-30', 'upcoming')], {
          state: 'refreshing',
        }),
      )
      .mockRejectedValueOnce(new Error('Still unavailable.'))
      .mockResolvedValueOnce(
        response([row('AAPL', '2026-08-01', 'upcoming')], {
          state: 'succeeded',
        }),
      )
    const rendered = render(<EarningsWatchPage />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByText('July 30, 2026')).toBeTruthy()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByText('July 30, 2026')).toBeTruthy()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByText('August 1, 2026')).toBeTruthy()

    rendered.unmount()
    const calls = api.fetchEarningsWatch.mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(api.fetchEarningsWatch).toHaveBeenCalledTimes(calls)
  })

  it('schedules cooldown and midnight reloads and resets sorting on reopen', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-06-18T03:59:00Z'))
    api.fetchEarningsWatch
      .mockResolvedValueOnce(
        response(
          [
            row('MSFT', '2026-08-01', 'upcoming'),
            row('AAPL', '2026-07-30', 'upcoming'),
          ],
          {
            state: 'cooldown',
            next_eligible_retry_at: '2026-06-18T03:59:01Z',
          },
        ),
      )
      .mockResolvedValueOnce(
        response([
          row('AAPL', '2026-07-30', 'upcoming'),
          row('MSFT', '2026-08-01', 'upcoming'),
        ]),
      )
      .mockResolvedValueOnce(
        response([
          row('MSFT', '2026-08-01', 'upcoming'),
          row('AAPL', '2026-07-30', 'upcoming'),
        ]),
      )
      .mockResolvedValueOnce(response([row('AAPL', '2026-07-30', 'upcoming')]))

    const first = render(<EarningsWatchPage />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    fireEvent.click(screen.getByRole('button', { name: /Earnings date/ }))
    expect(tickerCells()).toEqual(['AAPL', 'MSFT'])

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(api.fetchEarningsWatch).toHaveBeenCalledTimes(2)

    first.unmount()
    render(<EarningsWatchPage />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(tickerCells()).toEqual(['AAPL', 'MSFT'])

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(api.fetchEarningsWatch).toHaveBeenCalledTimes(4)
  })
})

function response(
  rows: EarningsWatchRow[],
  refresh: Partial<EarningsWatchResponse['refresh']> = {},
): EarningsWatchResponse {
  return {
    rows,
    refresh: {
      state: 'succeeded',
      last_attempt_at: '2026-06-18T12:00:00+00:00',
      last_success_at: '2026-06-18T12:00:00+00:00',
      last_success_date: '2026-06-18',
      error_category: null,
      next_eligible_retry_at: null,
      ...refresh,
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

function row(
  ticker: string,
  earningsDate: string | null,
  status: EarningsWatchRow['status'],
  reviewed = false,
): EarningsWatchRow {
  return {
    ticker,
    reviewed,
    earnings_date: earningsDate,
    status,
    created_at: `2026-06-18T12:00:00+00:00-${ticker}`,
    updated_at: '2026-06-18T12:00:00+00:00',
  }
}

function tableHeaders() {
  return screen
    .getAllByRole('columnheader')
    .map((header) => header.textContent?.replace(/[↑↓↕]/g, '').trim())
}

function tickerCells() {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((rowElement) => rowElement.querySelector('td')?.textContent ?? '')
}
