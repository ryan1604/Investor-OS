import { describe, expect, it } from 'vitest'

import {
  formatScreenerDelta,
  formatScreenerPercentage,
  formatScreenerPrice,
} from '@/features/options-screeners/lib/screenerResults'

describe('screener results', () => {
  it('formats displayed prices, signed deltas, and percentages to two decimals', () => {
    expect(formatScreenerPrice(1)).toBe('1.00')
    expect(formatScreenerPrice(1.025)).toBe('1.03')
    expect(formatScreenerDelta(-0.23456)).toBe('-0.23')
    expect(formatScreenerPercentage(12.3456)).toBe('12.35%')
  })

})
