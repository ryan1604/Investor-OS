import {
  valuationRowMetadata,
  type ValuationRowKey,
} from '@/features/stock-analysis/lib/valuationRows'

export function formatEditableValue(row: ValuationRowKey, value: number | null) {
  return value === null ? '' : formatValuationValue(row, value)
}

export function formatDisplayValue(row: ValuationRowKey, value: number | null) {
  return value === null ? '-' : formatValuationValue(row, value)
}

export function formatValuationValue(row: ValuationRowKey, value: number) {
  const formatKind = valuationRowMetadata(row)?.formatKind ?? 'number'

  if (formatKind === 'percent' || formatKind === 'ratioPercent') {
    const displayValue = formatKind === 'ratioPercent' ? value * 100 : value

    return `${formatNumber(displayValue, 2)}%`
  }

  if (formatKind === 'dollar') {
    return `$${formatNumber(value, 2)}`
  }

  if (formatKind === 'eps' || formatKind === 'multiple') {
    return formatNumber(value, 2)
  }

  return formatNumber(value, 0)
}

export function formatMultiplierValue(value: number | null) {
  return value === null ? '' : `${formatNumber(value * 100, 2)}%`
}

export function formatDraftValue(value: number | null) {
  return value === null ? '' : String(value)
}

function formatNumber(value: number, maximumFractionDigits: number) {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: maximumFractionDigits,
    maximumFractionDigits,
  }).format(value)
}
