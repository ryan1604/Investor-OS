import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const NativeNumberFormat = Intl.NumberFormat

beforeEach(() => vi.resetModules())
afterEach(() => vi.restoreAllMocks())

describe('number formatter cache', () => {
  it('separates currencies, precision, grouping, notation, and sign options', async () => {
    const { formatNumber } = await import('@/lib/format')
    const constructor = vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (locales, options) {
      return new NativeNumberFormat(locales, options)
    })
    const optionSets: Intl.NumberFormatOptions[] = [
      { style: 'currency', currency: 'USD' },
      { style: 'currency', currency: 'JPY' },
      { style: 'currency', currency: 'SGD', currencyDisplay: 'code' },
      { maximumFractionDigits: 0 },
      { minimumFractionDigits: 2, maximumFractionDigits: 2 },
      { useGrouping: false, maximumFractionDigits: 2 },
      { notation: 'compact', maximumFractionDigits: 1 },
      { style: 'percent', signDisplay: 'exceptZero', maximumFractionDigits: 2 },
    ]
    for (const options of optionSets) {
      const expected = new NativeNumberFormat('en-US', options).format(1234.567)
      expect(formatNumber(1234.567, options)).toBe(expected)
      expect(formatNumber(1234.567, { ...options })).toBe(expected)
    }
    expect(constructor).toHaveBeenCalledTimes(optionSets.length)
  })

  it('reuses identical options regardless of insertion order', async () => {
    const { formatNumber } = await import('@/lib/format')
    const constructor = vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (locales, options) {
      return new NativeNumberFormat(locales, options)
    })
    expect(formatNumber(12.5, { style: 'currency', currency: 'USD' })).toBe('$12.50')
    expect(formatNumber(13, { currency: 'USD', style: 'currency' })).toBe('$13.00')
    expect(constructor).toHaveBeenCalledTimes(1)
  })

  it('shares the default key for absent, empty, and undefined options', async () => {
    const { formatNumber } = await import('@/lib/format')
    const constructor = vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (locales, options) {
      return new NativeNumberFormat(locales, options)
    })
    expect(formatNumber(1234.5)).toBe('1,234.5')
    expect(formatNumber(1234.5, {})).toBe('1,234.5')
    expect(formatNumber(1234.5, { maximumFractionDigits: undefined })).toBe('1,234.5')
    expect(constructor).toHaveBeenCalledTimes(1)
  })
})

describe('formatter output compatibility', () => {
  it('keeps portfolio compact currency output for each currency and boundary value', async () => {
    const { formatCompactCurrency } = await import('@/lib/format')
    for (const currency of ['USD', 'SGD', 'JPY']) {
      for (const value of [0, -0, 0.01, -1, 999, 1000, 1250, -1250, 1_000_000, Infinity, -Infinity, NaN]) {
        expect(formatCompactCurrency(value, currency)).toBe(new NativeNumberFormat('en-US', {
          compactDisplay: 'short', currency, maximumFractionDigits: 1,
          notation: 'compact', style: 'currency',
        }).format(value))
      }
    }
    expect(formatCompactCurrency(null)).toBe('-')
  })

  it('keeps the tracker lowercase k notation even for millions and negatives', async () => {
    const { formatCompactCurrency } = await import('@/lib/format')
    const cases: [number, string][] = [
      [0, '$0.00'], [-0, '-$0.00'], [999.99, '$999.99'],
      [1000, '$1k'], [1250, '$1.3k'], [-1250, '-$1.3k'],
      [1_000_000, '$1,000k'], [Infinity, '$\u221ek'], [-Infinity, '-$\u221ek'],
    ]
    for (const [value, expected] of cases) {
      expect(formatCompactCurrency(value, 'USD', 'usd-thousands')).toBe(expected)
    }
  })

  it('keeps signed return percentages and their missing-value marker', async () => {
    const { formatReturnPercent } = await import('@/lib/format')
    for (const value of [0, -0, 0.12345, -0.12345, 1, NaN, Infinity]) {
      expect(formatReturnPercent(value)).toBe(new NativeNumberFormat('en-US', {
        maximumFractionDigits: 2, minimumFractionDigits: 2,
        signDisplay: 'exceptZero', style: 'percent',
      }).format(value))
    }
    expect(formatReturnPercent(null)).toBe('-')
  })

  it('preserves optional number, price, currency, and percentage formatting', async () => {
    const f = await import('@/lib/format')
    for (const value of [0, -0, 1.23456, -1234.56789, NaN, Infinity]) {
      expect(f.formatCurrency(value, 'SGD')).toBe(new NativeNumberFormat('en-US', {
        style: 'currency', currency: 'SGD',
      }).format(value))
      expect(f.formatOptionalCurrency(value)).toBe(f.formatCurrency(value))
      expect(f.formatOptionalPrice(value)).toBe(new NativeNumberFormat('en-US', {
        maximumFractionDigits: 2, minimumFractionDigits: 2,
      }).format(value))
      expect(f.formatOptionalDecimal(value)).toBe(new NativeNumberFormat('en-US', {
        maximumFractionDigits: 4, minimumFractionDigits: 2,
      }).format(value))
      expect(f.formatOptionalInteger(value)).toBe(new NativeNumberFormat('en-US', {
        maximumFractionDigits: 0,
      }).format(value))
      expect(f.formatOptionalPercent(value)).toBe(`${f.formatOptionalPrice(value)}%`)
    }
    for (const format of [f.formatOptionalCurrency, f.formatOptionalPercent,
      f.formatOptionalPrice, f.formatOptionalDecimal, f.formatOptionalInteger]) {
      expect(format(null)).toBe('-')
    }
  })
})
