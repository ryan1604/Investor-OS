import { describe, expect, it } from 'vitest'

import { optionReturnPercent } from '@/features/options/lib/optionReturns'

describe('optionReturns', () => {
  it('calculates call return from the latest underlying price', () => {
    expect(optionReturnPercent('call', 2.575, 95, 103)).toBe(2.5)
  })

  it('calculates put return from strike risk', () => {
    expect(optionReturnPercent('put', 1.9, 95, 103)).toBe(2)
  })

  it('keeps return missing when required prices are unavailable', () => {
    expect(optionReturnPercent('call', null, 95, 103)).toBeNull()
    expect(optionReturnPercent('call', 2.575, 95, null)).toBeNull()
    expect(optionReturnPercent('put', 1.9, 0, 103)).toBeNull()
  })
})
