import {
  DERIVED_ROW_DEFINITIONS,
  EDITABLE_ROW_DEFINITIONS,
  VALUATION_TABLE_ROW_DEFINITIONS,
  isFirstYearOnlyRow,
  type DerivedRowKey,
  type EditableRowKey,
  type SharePriceRowKey,
  type ValuationRowKey,
} from '@/features/stock-analysis/lib/valuationRows'

export const YEAR_COUNT = 5
export const YEAR_INDEXES = [0, 1, 2, 3, 4] as const

export const SCENARIO_KEYS = ['bull', 'base', 'bear'] as const

export type ScenarioKey = (typeof SCENARIO_KEYS)[number]
export type YearIndex = (typeof YEAR_INDEXES)[number]
export type ValuationCellKind = 'editable' | 'derived'
export type ValuationYearValues = [
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
]

export type ScenarioEditableInputs = Record<EditableRowKey, ValuationYearValues>
export type ScenarioDerivedValues = Record<DerivedRowKey, ValuationYearValues> &
  Pick<
    ScenarioEditableInputs,
    | 'amountOfShares'
    | 'revenue'
    | 'netIncome'
    | 'ebitda'
    | 'operatingCashFlow'
    | 'freeCashFlow'
  >

export type StockAnalysisValuationModel = {
  firstForecastYear: number | null
  currentPrice: number | null
  scenarios: Record<ScenarioKey, ScenarioEditableInputs>
}

export type StockAnalysisPayloadInput = {
  firstForecastYear?: unknown
  bull?: unknown
  base?: unknown
  bear?: unknown
}

export type CalculatedScenario = {
  editable: ScenarioEditableInputs
  derived: ScenarioDerivedValues
  multipliers: Record<SharePriceRowKey, number | null>
}

export type CalculatedStockAnalysisModel = {
  firstForecastYear: number | null
  yearHeaders: string[]
  scenarios: Record<ScenarioKey, CalculatedScenario>
}

export {
  DERIVED_ROW_DEFINITIONS,
  EDITABLE_ROW_DEFINITIONS,
  VALUATION_TABLE_ROW_DEFINITIONS,
  type DerivedRowKey,
  type EditableRowKey,
  type SharePriceRowKey,
  type ValuationRowKey,
}

export function createEmptyValuationModel(): StockAnalysisValuationModel {
  return {
    firstForecastYear: null,
    currentPrice: null,
    scenarios: Object.fromEntries(
      SCENARIO_KEYS.map((scenario) => [scenario, createEmptyScenarioInputs()]),
    ) as Record<ScenarioKey, ScenarioEditableInputs>,
  }
}

export function createEmptyScenarioInputs(): ScenarioEditableInputs {
  return Object.fromEntries(
    EDITABLE_ROW_DEFINITIONS.map((row) => [row.key, emptyYearValues()]),
  ) as ScenarioEditableInputs
}

export function stockAnalysisValuationModelFromPayload(
  payload: StockAnalysisPayloadInput,
  currentPrice: number | null = null,
): StockAnalysisValuationModel {
  const emptyModel = createEmptyValuationModel()

  return {
    firstForecastYear:
      typeof payload.firstForecastYear === 'number'
        ? payload.firstForecastYear
        : null,
    currentPrice,
    scenarios: Object.fromEntries(
      SCENARIO_KEYS.map((scenario) => [
        scenario,
        coerceScenarioInputs(payload[scenario], emptyModel.scenarios[scenario]),
      ]),
    ) as Record<ScenarioKey, ScenarioEditableInputs>,
  }
}

export function calculateValuationModel(
  model: StockAnalysisValuationModel,
): CalculatedStockAnalysisModel {
  return {
    firstForecastYear: model.firstForecastYear,
    yearHeaders: buildYearHeaders(model.firstForecastYear),
    scenarios: Object.fromEntries(
      SCENARIO_KEYS.map((scenario) => [
        scenario,
        calculateScenario(model.scenarios[scenario], model.currentPrice),
      ]),
    ) as Record<ScenarioKey, CalculatedScenario>,
  }
}

export function calculateScenario(
  inputs: ScenarioEditableInputs,
  currentPrice: number | null = null,
): CalculatedScenario {
  const amountOfShares = calculateGrownSeries(
    inputs.amountOfShares[0],
    inputs.sharesChangePercent,
  )
  const revenue = calculateGrownSeries(
    inputs.revenue[0],
    inputs.revenueGrowthPercent,
  )
  const netIncome = calculateGrownSeries(
    inputs.netIncome[0],
    inputs.netIncomeGrowthPercent,
  )
  const ebitda = calculateGrownSeries(inputs.ebitda[0], inputs.ebitdaGrowthPercent)
  const operatingCashFlow = calculateGrownSeries(
    inputs.operatingCashFlow[0],
    inputs.operatingCashFlowGrowthPercent,
  )
  const freeCashFlow = calculateGrownSeries(
    inputs.freeCashFlow[0],
    inputs.freeCashFlowGrowthPercent,
  )
  const eps = divideSeries(netIncome, amountOfShares)
  const sharePriceBasedOnPriceToSales = divideSeries(
    multiplySeries(revenue, inputs.priceToSales),
    amountOfShares,
  )
  const sharePriceEstimateLow = multiplySeries(eps, inputs.peEstimateLow)
  const sharePriceBasedOnPriceToEbitda = divideSeries(
    multiplySeries(ebitda, inputs.priceToEbitda),
    amountOfShares,
  )
  const sharePriceBasedOnPriceToOperatingCashFlow = divideSeries(
    multiplySeries(operatingCashFlow, inputs.priceToOperatingCashFlow),
    amountOfShares,
  )
  const sharePriceBasedOnPriceToFreeCashFlow = divideSeries(
    multiplySeries(freeCashFlow, inputs.priceToFreeCashFlow),
    amountOfShares,
  )

  return {
    editable: inputs,
    derived: {
      amountOfShares,
      revenue,
      netIncome,
      ebitda,
      operatingCashFlow,
      freeCashFlow,
      netIncomeMargin: divideSeries(netIncome, revenue),
      eps,
      ebitdaMargin: divideSeries(ebitda, revenue),
      operatingCashFlowMargin: divideSeries(operatingCashFlow, revenue),
      freeCashFlowMargin: divideSeries(freeCashFlow, revenue),
      sharePriceBasedOnPriceToSales,
      sharePriceBasedOnPriceToSalesCagr: calculateCagrSeries(
        sharePriceBasedOnPriceToSales,
        currentPrice,
      ),
      sharePriceEstimateLow,
      sharePriceEstimateLowCagr: calculateCagrSeries(
        sharePriceEstimateLow,
        currentPrice,
      ),
      sharePriceBasedOnPriceToEbitda,
      sharePriceBasedOnPriceToEbitdaCagr: calculateCagrSeries(
        sharePriceBasedOnPriceToEbitda,
        currentPrice,
      ),
      sharePriceBasedOnPriceToOperatingCashFlow,
      sharePriceBasedOnPriceToOperatingCashFlowCagr: calculateCagrSeries(
        sharePriceBasedOnPriceToOperatingCashFlow,
        currentPrice,
      ),
      sharePriceBasedOnPriceToFreeCashFlow,
      sharePriceBasedOnPriceToFreeCashFlowCagr: calculateCagrSeries(
        sharePriceBasedOnPriceToFreeCashFlow,
        currentPrice,
      ),
    },
    multipliers: {
      sharePriceBasedOnPriceToSales: calculateMultiplier(
        sharePriceBasedOnPriceToSales[4],
        currentPrice,
      ),
      sharePriceEstimateLow: calculateMultiplier(
        sharePriceEstimateLow[4],
        currentPrice,
      ),
      sharePriceBasedOnPriceToEbitda: calculateMultiplier(
        sharePriceBasedOnPriceToEbitda[4],
        currentPrice,
      ),
      sharePriceBasedOnPriceToOperatingCashFlow: calculateMultiplier(
        sharePriceBasedOnPriceToOperatingCashFlow[4],
        currentPrice,
      ),
      sharePriceBasedOnPriceToFreeCashFlow: calculateMultiplier(
        sharePriceBasedOnPriceToFreeCashFlow[4],
        currentPrice,
      ),
    },
  }
}

export function buildYearHeaders(firstForecastYear: number | null) {
  if (firstForecastYear === null) {
    return YEAR_INDEXES.map((yearIndex) => `Year ${yearIndex + 1}`)
  }

  return YEAR_INDEXES.map((yearIndex) => String(firstForecastYear + yearIndex))
}

export function getValuationCellKind(
  row: ValuationRowKey,
  yearIndex: YearIndex,
): ValuationCellKind {
  if (isDerivedRow(row)) {
    return 'derived'
  }

  if (isFirstYearOnlyRow(row) && yearIndex > 0) {
    return 'derived'
  }

  return 'editable'
}

function calculateGrownSeries(
  yearOneValue: number | null,
  growthPercentages: ValuationYearValues,
): ValuationYearValues {
  const values = emptyYearValues()
  values[0] = yearOneValue

  for (const yearIndex of YEAR_INDEXES.slice(1)) {
    const previousValue = values[yearIndex - 1]
    const growthPercentage = growthPercentages[yearIndex]
    values[yearIndex] =
      previousValue === null || growthPercentage === null
        ? null
        : normalizeCalculatedNumber(previousValue * (1 + growthPercentage / 100))
  }

  return values
}

function coerceScenarioInputs(
  value: unknown,
  fallback: ScenarioEditableInputs,
): ScenarioEditableInputs {
  if (!value || typeof value !== 'object') {
    return fallback
  }

  const scenarioValue = value as Record<string, unknown>

  return Object.fromEntries(
    Object.entries(fallback).map(([row, fallbackValues]) => [
      row,
      coerceYearValues(scenarioValue[row], fallbackValues),
    ]),
  ) as ScenarioEditableInputs
}

function coerceYearValues(
  value: unknown,
  fallback: ValuationYearValues,
): ValuationYearValues {
  if (!Array.isArray(value)) {
    return fallback
  }

  return YEAR_INDEXES.map((yearIndex) => {
    const cellValue = value[yearIndex]
    return typeof cellValue === 'number' && Number.isFinite(cellValue)
      ? cellValue
      : null
  }) as ValuationYearValues
}

function divideSeries(
  numerators: ValuationYearValues,
  denominators: ValuationYearValues,
): ValuationYearValues {
  return mapYearValues((yearIndex) =>
    divide(numerators[yearIndex], denominators[yearIndex]),
  )
}

function multiplySeries(
  firstValues: ValuationYearValues,
  secondValues: ValuationYearValues,
): ValuationYearValues {
  return mapYearValues((yearIndex) => {
    const firstValue = firstValues[yearIndex]
    const secondValue = secondValues[yearIndex]

    return firstValue === null || secondValue === null
      ? null
      : normalizeCalculatedNumber(firstValue * secondValue)
  })
}

function divide(numerator: number | null, denominator: number | null) {
  if (numerator === null || denominator === null || denominator === 0) {
    return null
  }

  return normalizeCalculatedNumber(numerator / denominator)
}

function calculateCagrSeries(
  sharePrices: ValuationYearValues,
  currentPrice: number | null,
): ValuationYearValues {
  return mapYearValues((yearIndex) => {
    if (yearIndex < 2) {
      return null
    }

    const sharePrice = sharePrices[yearIndex]
    if (sharePrice === null || currentPrice === null || currentPrice <= 0) {
      return null
    }

    return normalizeCalculatedNumber(
      (sharePrice / currentPrice) ** (1 / (yearIndex + 1)) - 1,
    )
  })
}

function calculateMultiplier(
  sharePrice: number | null,
  currentPrice: number | null,
) {
  if (sharePrice === null || currentPrice === null || currentPrice <= 0) {
    return null
  }

  return normalizeCalculatedNumber(sharePrice / currentPrice - 1)
}

function normalizeCalculatedNumber(value: number) {
  return Math.round((value + Number.EPSILON) * 1_000_000_000_000) / 1_000_000_000_000
}

function emptyYearValues(): ValuationYearValues {
  return [null, null, null, null, null]
}

function mapYearValues(
  mapper: (yearIndex: YearIndex) => number | null,
): ValuationYearValues {
  return YEAR_INDEXES.map((yearIndex) => mapper(yearIndex)) as ValuationYearValues
}

function isDerivedRow(row: ValuationRowKey): row is DerivedRowKey {
  return DERIVED_ROW_DEFINITIONS.some(
    (derivedRowDefinition) => derivedRowDefinition.key === row,
  )
}
