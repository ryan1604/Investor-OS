import type { StockAnalysisModel } from '@/api/stockAnalysis'
import {
  SCENARIO_KEYS,
  calculateValuationModel,
  stockAnalysisValuationModelFromPayload,
  type CalculatedStockAnalysisModel,
  type ScenarioKey,
} from '@/features/stock-analysis/lib/valuationModel'
import type { SharePriceRowKey } from '@/features/stock-analysis/lib/valuationRows'

export const METRICS: {
  key: SharePriceRowKey
  label: string
}[] = [
  { key: 'sharePriceBasedOnPriceToSales', label: 'P/S' },
  { key: 'sharePriceEstimateLow', label: 'P/E' },
  { key: 'sharePriceBasedOnPriceToEbitda', label: 'P/EBITDA' },
  { key: 'sharePriceBasedOnPriceToOperatingCashFlow', label: 'P/OCF' },
  { key: 'sharePriceBasedOnPriceToFreeCashFlow', label: 'P/FCF' },
]

export type RankingRow = {
  ticker: string
  returnPercent: number | null
}

export function buildRankings(models: StockAnalysisModel[]) {
  const calculatedModels = models.map((model) => ({
    ticker: model.ticker,
    calculated: calculateValuationModel(stockAnalysisValuationModelFromPayload(
      model.payload,
      model.current_price,
    )),
  }))
  return Object.fromEntries(
    SCENARIO_KEYS.map((scenario) => [
      scenario,
      Object.fromEntries(
        METRICS.map((metric) => [
          metric.key,
          calculatedModels
            .map((model) => rankingRow(model.ticker, model.calculated, scenario, metric.key))
            .sort(compareRankingRows),
        ]),
      ),
    ]),
  ) as Record<ScenarioKey, Record<SharePriceRowKey, RankingRow[]>>
}

function rankingRow(
  ticker: string,
  calculatedModel: CalculatedStockAnalysisModel,
  scenario: ScenarioKey,
  metric: SharePriceRowKey,
): RankingRow {
  return {
    ticker,
    returnPercent: calculatedModel.scenarios[scenario].multipliers[metric],
  }
}

function compareRankingRows(first: RankingRow, second: RankingRow) {
  if (first.returnPercent === null && second.returnPercent === null) {
    return first.ticker.localeCompare(second.ticker)
  }

  if (first.returnPercent === null) {
    return 1
  }

  if (second.returnPercent === null) {
    return -1
  }

  return second.returnPercent - first.returnPercent
}

