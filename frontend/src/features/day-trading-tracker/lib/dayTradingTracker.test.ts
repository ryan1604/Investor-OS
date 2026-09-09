import { describe, expect, it } from 'vitest'

import {
  buildMonthWeeks,
  calculateDayTradingStats,
  calculateMonthlyDayTradingStats,
  canNavigateNext,
  canNavigatePrevious,
  completedDayTrades,
  initialMonth,
  newDayTradeDraftRow,
  requestRowsFromDraftRows,
  validateDayTradeDraftRows,
} from '@/features/day-trading-tracker/lib/dayTradingTracker'

describe('dayTradingTracker', () => {
  it('bounds initial month and month navigation', () => {
    expect(initialMonth('2026-08-20')).toBe('2026-08')
    expect(initialMonth('2026-12-05')).toBe('2026-12')
    expect(canNavigatePrevious('2026-08')).toBe(false)
    expect(canNavigatePrevious('2026-09')).toBe(true)
    expect(canNavigateNext('2026-08', '2026-08-20')).toBe(false)
    expect(canNavigateNext('2026-08', '2026-09-01')).toBe(true)
  })

  it('builds a Monday-first calendar with disabled out-of-range days', () => {
    const weeks = buildMonthWeeks('2026-08', '2026-08-20')
    const firstDay = weeks[0][0]
    const augustFirst = weeks[0][5]
    const augustTwentieth = weeks[3][3]
    const augustTwentyFirst = weeks[3][4]

    expect(firstDay.date).toBe('2026-07-27')
    expect(firstDay.isAllowed).toBe(false)
    expect(augustFirst.date).toBe('2026-08-01')
    expect(augustFirst.isAllowed).toBe(true)
    expect(augustTwentieth.date).toBe('2026-08-20')
    expect(augustTwentieth.isAllowed).toBe(true)
    expect(augustTwentyFirst.date).toBe('2026-08-21')
    expect(augustTwentyFirst.isAllowed).toBe(false)
  })

  it('calculates daily pnl, commission, wins, losses, and flats', () => {
    const stats = calculateDayTradingStats([
      { ...newDayTradeDraftRow('row-1'), buy: '10', sell: '12', size: '2', fee: '1' },
      { ...newDayTradeDraftRow('row-2'), buy: '10', sell: '9', size: '1', fee: '2' },
      { ...newDayTradeDraftRow('row-3'), buy: '10', sell: '10', size: '3' },
      { ...newDayTradeDraftRow('row-4'), buy: 'bad', sell: '11', size: '1' },
    ])

    expect(stats).toEqual({
      completedTrades: 3,
      wins: 1,
      losses: 1,
      winRate: 0.5,
      pnl: 280,
    })
  })

  it('calculates monthly stats from daily rows', () => {
    const stats = calculateMonthlyDayTradingStats({
      '2026-08-01': [
        { ...newDayTradeDraftRow('row-1'), buy: '10', sell: '12', size: '1' },
      ],
      '2026-08-02': [
        { ...newDayTradeDraftRow('row-2'), buy: '10', sell: '9', size: '1' },
      ],
    })

    expect(stats.completedTrades).toBe(2)
    expect(stats.wins).toBe(1)
    expect(stats.losses).toBe(1)
    expect(stats.winDays).toBe(1)
    expect(stats.lossDays).toBe(1)
    expect(stats.pnl).toBe(92)
  })

  it('validates malformed drafts but excludes incomplete rows from calculations', () => {
    const rows = [
      { ...newDayTradeDraftRow('row-1'), buy: '10', sell: '', size: '' },
      { ...newDayTradeDraftRow('row-2'), buy: 'bad', sell: '11', size: '1.5', fee: '-1' },
    ]

    expect(completedDayTrades(rows)).toEqual([])
    expect(validateDayTradeDraftRows(rows)).toEqual([
      {
        localId: 'row-2',
        field: 'buy',
        message: 'Buy must be a valid number.',
      },
      {
        localId: 'row-2',
        field: 'size',
        message: 'Size must be a positive whole number.',
      },
      {
        localId: 'row-2',
        field: 'fee',
        message: 'Fee must be zero or greater.',
      },
    ])
  })

  it('projects draft rows to replace-date requests', () => {
    expect(
      requestRowsFromDraftRows([
        { ...newDayTradeDraftRow('row-1'), id: 'saved-1', buy: '10', sell: '', size: '2' },
      ]),
    ).toEqual([
      {
        id: 'saved-1',
        display_order: 1,
        buy: 10,
        sell: null,
        size: 2,
        fee: 2,
      },
    ])
  })
})
