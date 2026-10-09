const numberFormatters = new Map<string, Intl.NumberFormat>()

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
) {
  const key = JSON.stringify(
    Object.entries(options ?? {})
      .filter(([, value]) => value !== undefined)
      .sort(([first], [second]) => first.localeCompare(second)),
  )
  let formatter = numberFormatters.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat('en-US', options)
    numberFormatters.set(key, formatter)
  }
  return formatter.format(value)
}

export function formatCurrency(value: number, currency = 'USD') {
  return formatNumber(value, {
    style: 'currency',
    currency,
  })
}

export function formatPercentValue(value: number) {
  return `${formatNumber(value, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}%`
}

export function formatOptionalCurrency(value: number | null, currency = 'USD') {
  if (value === null) {
    return '-'
  }

  return formatCurrency(value, currency)
}

export function formatOptionalPercent(value: number | null) {
  if (value === null) {
    return '-'
  }

  return formatPercentValue(value)
}

export function formatOptionalPrice(value: number | null) {
  if (value === null) {
    return '-'
  }

  return formatNumber(value, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })
}

export function formatOptionalDecimal(value: number | null) {
  if (value === null) {
    return '-'
  }

  return formatNumber(value, {
    maximumFractionDigits: 4,
    minimumFractionDigits: 2,
  })
}

export function formatOptionalInteger(value: number | null) {
  if (value === null) {
    return '-'
  }

  return formatNumber(value, {
    maximumFractionDigits: 0,
  })
}

export function signedValueClassName(value: number | null) {
  if (value === null || value === 0) {
    return 'text-right'
  }

  return value > 0 ? 'text-right text-emerald-400' : 'text-right text-red-400'
}

export function signedTextClassName(value: number | null) {
  if (value === null || value === 0) {
    return 'text-foreground'
  }

  return value > 0 ? 'text-emerald-500' : 'text-red-500'
}

export function formatCompactCurrency(
  value: number | null,
  currency = 'USD',
  mode: 'compact' | 'usd-thousands' = 'compact',
) {
  if (value === null) {
    return '-'
  }

  if (mode === 'usd-thousands') {
    const absoluteValue = Math.abs(value)
    if (absoluteValue >= 1000) {
      return `${value < 0 ? '-' : ''}$${formatNumber(absoluteValue / 1000, {
        maximumFractionDigits: 1,
      })}k`
    }
    return formatCurrency(value)
  }

  return formatNumber(value, {
    compactDisplay: 'short',
    currency,
    maximumFractionDigits: 1,
    notation: 'compact',
    style: 'currency',
  })
}

export function formatReturnPercent(value: number | null) {
  if (value === null) {
    return '-'
  }

  return formatNumber(value, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    signDisplay: 'exceptZero',
    style: 'percent',
  })
}
