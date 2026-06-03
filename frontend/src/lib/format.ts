export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
) {
  return new Intl.NumberFormat('en-US', options).format(value)
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
