const VALUATION_ROW_REGISTRY = [
  {
    key: 'amountOfShares',
    label: 'Amount of shares',
    source: 'editable',
    firstYearOnly: true,
    formatKind: 'number',
  },
  {
    key: 'sharesChangePercent',
    label: 'Shares percentage change',
    source: 'editable',
    formatKind: 'percent',
  },
  {
    key: 'revenue',
    label: 'Revenue',
    source: 'editable',
    firstYearOnly: true,
    formatKind: 'dollar',
  },
  {
    key: 'revenueGrowthPercent',
    label: 'Revenue growth',
    source: 'editable',
    formatKind: 'percent',
    spacerAfter: true,
  },
  {
    key: 'netIncome',
    label: 'Net income',
    source: 'editable',
    firstYearOnly: true,
    formatKind: 'dollar',
  },
  {
    key: 'netIncomeMargin',
    label: 'Net income margin',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'netIncomeGrowthPercent',
    label: 'Net income growth',
    source: 'editable',
    formatKind: 'percent',
  },
  {
    key: 'eps',
    label: 'EPS',
    source: 'derived',
    formatKind: 'eps',
    spacerAfter: true,
  },
  {
    key: 'ebitda',
    label: 'EBITDA',
    source: 'editable',
    firstYearOnly: true,
    formatKind: 'dollar',
  },
  {
    key: 'ebitdaMargin',
    label: 'EBITDA margin',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'ebitdaGrowthPercent',
    label: 'EBITDA growth',
    source: 'editable',
    formatKind: 'percent',
    spacerAfter: true,
  },
  {
    key: 'operatingCashFlow',
    label: 'OCF',
    source: 'editable',
    firstYearOnly: true,
    formatKind: 'dollar',
  },
  {
    key: 'operatingCashFlowMargin',
    label: 'OCF margin',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'operatingCashFlowGrowthPercent',
    label: 'OCF growth',
    source: 'editable',
    formatKind: 'percent',
    spacerAfter: true,
  },
  {
    key: 'freeCashFlow',
    label: 'FCF',
    source: 'editable',
    firstYearOnly: true,
    formatKind: 'dollar',
  },
  {
    key: 'freeCashFlowMargin',
    label: 'FCF margin',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'freeCashFlowGrowthPercent',
    label: 'FCF growth',
    source: 'editable',
    formatKind: 'percent',
    spacerAfter: true,
  },
  { key: 'priceToSales', label: 'P/S', source: 'editable', formatKind: 'multiple' },
  {
    key: 'peEstimateLow',
    label: 'P/E',
    source: 'editable',
    formatKind: 'multiple',
  },
  {
    key: 'priceToEbitda',
    label: 'P/EBITDA',
    source: 'editable',
    formatKind: 'multiple',
  },
  {
    key: 'priceToOperatingCashFlow',
    label: 'P/OCF',
    source: 'editable',
    formatKind: 'multiple',
  },
  {
    key: 'priceToFreeCashFlow',
    label: 'P/FCF',
    source: 'editable',
    formatKind: 'multiple',
    spacerAfter: true,
  },
  {
    key: 'sharePriceBasedOnPriceToSales',
    label: 'Share price based on P/S',
    source: 'derived',
    formatKind: 'dollar',
    hasMultiplier: true,
  },
  {
    key: 'sharePriceBasedOnPriceToSalesCagr',
    label: 'CAGR',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'sharePriceEstimateLow',
    label: 'Share price based on P/E',
    source: 'derived',
    formatKind: 'dollar',
    hasMultiplier: true,
  },
  {
    key: 'sharePriceEstimateLowCagr',
    label: 'CAGR',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'sharePriceBasedOnPriceToEbitda',
    label: 'Share price based on P/EBITDA',
    source: 'derived',
    formatKind: 'dollar',
    hasMultiplier: true,
  },
  {
    key: 'sharePriceBasedOnPriceToEbitdaCagr',
    label: 'CAGR',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'sharePriceBasedOnPriceToOperatingCashFlow',
    label: 'Share price based on P/OCF',
    source: 'derived',
    formatKind: 'dollar',
    hasMultiplier: true,
  },
  {
    key: 'sharePriceBasedOnPriceToOperatingCashFlowCagr',
    label: 'CAGR',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
  {
    key: 'sharePriceBasedOnPriceToFreeCashFlow',
    label: 'Share price based on P/FCF',
    source: 'derived',
    formatKind: 'dollar',
    hasMultiplier: true,
  },
  {
    key: 'sharePriceBasedOnPriceToFreeCashFlowCagr',
    label: 'CAGR',
    source: 'derived',
    formatKind: 'ratioPercent',
  },
] as const

type ValuationRowDefinition = (typeof VALUATION_ROW_REGISTRY)[number]
export type ValuationRowKey = ValuationRowDefinition['key']
export type EditableRowKey = Extract<
  ValuationRowDefinition,
  { source: 'editable' }
>['key']
export type DerivedRowKey = Extract<
  ValuationRowDefinition,
  { source: 'derived' }
>['key']
export type SharePriceRowKey = Extract<
  ValuationRowDefinition,
  { hasMultiplier: true }
>['key']

export const EDITABLE_ROW_DEFINITIONS = VALUATION_ROW_REGISTRY.filter(
  (row): row is Extract<ValuationRowDefinition, { source: 'editable' }> =>
    row.source === 'editable',
)

export const DERIVED_ROW_DEFINITIONS = VALUATION_ROW_REGISTRY.filter(
  (row): row is Extract<ValuationRowDefinition, { source: 'derived' }> =>
    row.source === 'derived',
)

export const VALUATION_TABLE_ROW_DEFINITIONS = VALUATION_ROW_REGISTRY

export function valuationRowMetadata(row: ValuationRowKey) {
  return VALUATION_ROW_REGISTRY.find((definition) => definition.key === row)
}

export function isSharePriceRow(row: ValuationRowKey): row is SharePriceRowKey {
  const metadata = valuationRowMetadata(row)
  return Boolean(metadata && 'hasMultiplier' in metadata && metadata.hasMultiplier)
}

export function hasSpacerAfter(row: ValuationRowKey) {
  const metadata = valuationRowMetadata(row)
  return Boolean(metadata && 'spacerAfter' in metadata && metadata.spacerAfter)
}

export function isFirstYearOnlyRow(row: ValuationRowKey) {
  const metadata = valuationRowMetadata(row)
  return Boolean(metadata && 'firstYearOnly' in metadata && metadata.firstYearOnly)
}
