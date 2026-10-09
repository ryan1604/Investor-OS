import { describe, expect, it } from 'vitest'

import {
  defaultSingleLegFilters,
  filterDraftFromSettings,
  parseUncheckedScreenerTickers,
  validateFilterDraft,
} from '@/features/options-screeners/lib/screenerSettings'

describe('screener settings', () => {
  it('normalizes pasted ticker input while preserving first-seen order', () => {
    expect(parseUncheckedScreenerTickers(' aapl, MSFT\nnvda aapl ')).toEqual([
      'AAPL',
      'MSFT',
      'NVDA',
    ])
  })

  it('keeps invalid drafts local and parses valid inclusive ranges', () => {
    expect(
      validateFilterDraft({
        ...filterDraftFromSettings(defaultSingleLegFilters),
        minimum_dte: '46',
      }),
    ).toMatchObject({ filters: null })

    expect(
      validateFilterDraft(filterDraftFromSettings(defaultSingleLegFilters)),
    ).toEqual({ filters: defaultSingleLegFilters, error: null })
  })

  it('rejects blank numeric fields instead of coercing them to zero', () => {
    expect(
      validateFilterDraft({
        ...filterDraftFromSettings(defaultSingleLegFilters),
        minimum_annualized_return: '',
      }),
    ).toEqual({
      filters: null,
      error: 'Enter a number in every filter field.',
    })
  })
})
