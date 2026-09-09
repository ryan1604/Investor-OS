// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchDayTradingMonth,
  replaceDayTradingDateTrades,
} from '@/api/dayTradingTracker'
import { DayTradingTrackerPage } from '@/features/day-trading-tracker/DayTradingTrackerPage'

vi.mock('@/api/dayTradingTracker', () => ({
  fetchDayTradingMonth: vi.fn(),
  replaceDayTradingDateTrades: vi.fn(),
}))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 7, 20, 12))
  vi.mocked(fetchDayTradingMonth).mockResolvedValue({
    month: '2026-08',
    days: [
      {
        date: '2026-08-19',
        trades: [
          {
            id: 'row-1',
            display_order: 1,
            buy: 10,
            sell: 12,
            size: 1,
            fee: 2,
            created_at: '',
            updated_at: '',
          },
        ],
      },
    ],
  })
  vi.mocked(replaceDayTradingDateTrades).mockImplementation((date, request) =>
    Promise.resolve({
      date,
      trades: request.trades.map((row, index) => ({
        id: row.id ?? `saved-${index + 1}`,
        display_order: row.display_order,
        buy: row.buy ?? null,
        sell: row.sell ?? null,
        size: row.size ?? null,
        fee: row.fee ?? null,
        created_at: '',
        updated_at: '',
      })),
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('DayTradingTrackerPage', () => {
  it('renders bounded calendar stats and disables future navigation', async () => {
    render(<DayTradingTrackerPage />)

    expect(await screen.findByText('August 2026')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Previous month' })).toHaveProperty(
      'disabled',
      true,
    )
    expect(screen.getByRole('button', { name: 'Next month' })).toHaveProperty(
      'disabled',
      true,
    )
    expect(screen.getAllByText('$196.00').length).toBeGreaterThan(0)
    expect(screen.getByText('1 trades')).toBeTruthy()
    expect(screen.getByText('W: 1 L: 0')).toBeTruthy()
    expect(screen.getAllByText('(100.00%)').length).toBeGreaterThan(0)
    expect(
      screen.getByRole('button', { name: 'Open trades for 2026-08-20' }),
    ).toBeTruthy()
    expect(
      screen.queryByRole('button', { name: 'Open trades for 2026-08-21' }),
    ).toBeNull()
  })

  it('opens a date, adds rows, saves, and updates summaries', async () => {
    render(<DayTradingTrackerPage />)

    fireEvent.click(
      await screen.findByRole('button', { name: 'Open trades for 2026-08-20' }),
    )
    expect(screen.getByText('2026-08-20')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText('Buy row 1'), {
      target: { value: '10' },
    })
    fireEvent.change(screen.getByLabelText('Sell row 1'), {
      target: { value: '11' },
    })
    fireEvent.change(screen.getByLabelText('Size row 1'), {
      target: { value: '2' },
    })
    fireEvent.change(screen.getByLabelText('Fee row 1'), {
      target: { value: '1.5' },
    })
    expect(screen.getAllByText('$194.00').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))

    await waitFor(() => {
      expect(replaceDayTradingDateTrades).toHaveBeenCalledWith(
        '2026-08-20',
        {
          trades: [
            {
              id: null,
              display_order: 1,
              buy: 10,
              sell: 11,
              size: 2,
              fee: 1.5,
            },
          ],
        },
      )
    })
    expect(screen.getAllByText('$194.00').length).toBeGreaterThan(0)
  })

  it('preserves unsaved drafts while switching dates', async () => {
    render(<DayTradingTrackerPage />)

    fireEvent.click(
      await screen.findByRole('button', { name: 'Open trades for 2026-08-20' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText('Buy row 1'), {
      target: { value: '15' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Open trades for 2026-08-19' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open trades for 2026-08-20' }))

    expect((screen.getByLabelText('Buy row 1') as HTMLInputElement).value).toBe(
      '15',
    )
    expect(replaceDayTradingDateTrades).not.toHaveBeenCalled()
  })
})
