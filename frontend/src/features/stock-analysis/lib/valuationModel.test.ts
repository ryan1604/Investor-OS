import { describe, expect, it } from 'vitest'

import {
  SCENARIO_KEYS,
  calculateScenario,
  calculateValuationModel,
  createEmptyValuationModel,
  getValuationCellKind,
  stockAnalysisValuationModelFromPayload,
  type ScenarioEditableInputs,
} from '@/features/stock-analysis/lib/valuationModel'
import {
  hasSpacerAfter,
  isSharePriceRow,
  valuationRowMetadata,
} from '@/features/stock-analysis/lib/valuationRows'

describe('valuationModel', () => {
  it('creates identical editable row structures for bull, base, and bear', () => {
    const model = createEmptyValuationModel()
    const rowKeys = Object.keys(model.scenarios.bull)

    expect(model.firstForecastYear).toBeNull()
    expect(model.currentPrice).toBeNull()
    expect(SCENARIO_KEYS).toEqual(['bull', 'base', 'bear'])
    expect(Object.keys(model.scenarios.base)).toEqual(rowKeys)
    expect(Object.keys(model.scenarios.bear)).toEqual(rowKeys)
    expect(model.scenarios.bull.revenue).toEqual([null, null, null, null, null])
  })

  it('builds placeholder and consecutive year headers from one shared first year', () => {
    const emptyModel = calculateValuationModel(createEmptyValuationModel())
    const model = createEmptyValuationModel()
    model.firstForecastYear = 2027

    expect(emptyModel.yearHeaders).toEqual([
      'Year 1',
      'Year 2',
      'Year 3',
      'Year 4',
      'Year 5',
    ])
    expect(calculateValuationModel(model).yearHeaders).toEqual([
      '2027',
      '2028',
      '2029',
      '2030',
      '2031',
    ])
  })

  it('separates editable and derived cells in mixed valuation rows', () => {
    expect(getValuationCellKind('amountOfShares', 0)).toBe('editable')
    expect(getValuationCellKind('amountOfShares', 1)).toBe('derived')
    expect(getValuationCellKind('sharesChangePercent', 0)).toBe('editable')
    expect(getValuationCellKind('sharesChangePercent', 4)).toBe('editable')
    expect(getValuationCellKind('priceToSales', 4)).toBe('editable')
    expect(getValuationCellKind('eps', 0)).toBe('derived')
  })

  it('calculates share counts and financial rows from year two growth onward', () => {
    const result = calculateScenario(
      scenarioInputs({
        amountOfShares: [100, null, null, null, null],
        sharesChangePercent: [99, 10, -5, 0, 20],
        revenue: [1_000, null, null, null, null],
        revenueGrowthPercent: [99, 20, 10, -10, 0],
        netIncome: [100, null, null, null, null],
        netIncomeGrowthPercent: [99, 50, 0, -20, 25],
        ebitda: [180, null, null, null, null],
        ebitdaGrowthPercent: [99, 15, 10, 0, -5],
        operatingCashFlow: [120, null, null, null, null],
        operatingCashFlowGrowthPercent: [99, 10, 10, 10, 10],
        freeCashFlow: [80, null, null, null, null],
        freeCashFlowGrowthPercent: [99, 25, 0, -10, 10],
      }),
    )

    expect(result.derived.amountOfShares).toEqual([100, 110, 104.5, 104.5, 125.4])
    expect(result.derived.revenue).toEqual([1_000, 1_200, 1_320, 1_188, 1_188])
    expect(result.derived.netIncome).toEqual([100, 150, 150, 120, 150])
    expect(result.derived.ebitda).toEqual([180, 207, 227.7, 227.7, 216.315])
    expect(result.derived.operatingCashFlow).toEqual([
      120,
      132,
      145.2,
      159.72,
      175.692,
    ])
    expect(result.derived.freeCashFlow).toEqual([80, 100, 100, 90, 99])
  })

  it('calculates margins and EPS from derived fundamentals', () => {
    const result = calculateScenario(
      scenarioInputs({
        amountOfShares: [100, null, null, null, null],
        sharesChangePercent: [0, 0, 0, 0, 0],
        revenue: [1_000, null, null, null, null],
        revenueGrowthPercent: [0, 0, 0, 0, 0],
        netIncome: [100, null, null, null, null],
        netIncomeGrowthPercent: [0, 0, 0, 0, 0],
        ebitda: [250, null, null, null, null],
        ebitdaGrowthPercent: [0, 0, 0, 0, 0],
        operatingCashFlow: [200, null, null, null, null],
        operatingCashFlowGrowthPercent: [0, 0, 0, 0, 0],
        freeCashFlow: [150, null, null, null, null],
        freeCashFlowGrowthPercent: [0, 0, 0, 0, 0],
      }),
    )

    expect(result.derived.netIncomeMargin).toEqual([0.1, 0.1, 0.1, 0.1, 0.1])
    expect(result.derived.ebitdaMargin).toEqual([
      0.25,
      0.25,
      0.25,
      0.25,
      0.25,
    ])
    expect(result.derived.operatingCashFlowMargin).toEqual([
      0.2,
      0.2,
      0.2,
      0.2,
      0.2,
    ])
    expect(result.derived.freeCashFlowMargin).toEqual([
      0.15,
      0.15,
      0.15,
      0.15,
      0.15,
    ])
    expect(result.derived.eps).toEqual([1, 1, 1, 1, 1])
  })

  it('calculates share prices from sales, PE, EBITDA, operating cash flow, and free cash flow multiples', () => {
    const result = calculateScenario(
      scenarioInputs({
        amountOfShares: [100, null, null, null, null],
        sharesChangePercent: [0, 0, 0, 0, 0],
        revenue: [1_000, null, null, null, null],
        revenueGrowthPercent: [0, 0, 0, 0, 0],
        netIncome: [100, null, null, null, null],
        netIncomeGrowthPercent: [0, 0, 0, 0, 0],
        ebitda: [250, null, null, null, null],
        ebitdaGrowthPercent: [0, 0, 0, 0, 0],
        operatingCashFlow: [200, null, null, null, null],
        operatingCashFlowGrowthPercent: [0, 0, 0, 0, 0],
        freeCashFlow: [150, null, null, null, null],
        freeCashFlowGrowthPercent: [0, 0, 0, 0, 0],
        priceToSales: [2, 3, 4, 5, 6],
        peEstimateLow: [10, 11, 12, 13, 14],
        priceToEbitda: [4, 5, 6, 7, 8],
        priceToOperatingCashFlow: [5, 6, 7, 8, 9],
        priceToFreeCashFlow: [8, 9, 10, 11, 12],
      }),
    )

    expect(result.derived.sharePriceBasedOnPriceToSales).toEqual([
      20,
      30,
      40,
      50,
      60,
    ])
    expect(result.derived.sharePriceEstimateLow).toEqual([10, 11, 12, 13, 14])
    expect(result.derived.sharePriceBasedOnPriceToEbitda).toEqual([
      10,
      12.5,
      15,
      17.5,
      20,
    ])
    expect(result.derived.sharePriceBasedOnPriceToOperatingCashFlow).toEqual([
      10,
      12,
      14,
      16,
      18,
    ])
    expect(result.derived.sharePriceBasedOnPriceToFreeCashFlow).toEqual([
      12,
      13.5,
      15,
      16.5,
      18,
    ])
  })

  it('calculates CAGR rows and year five multipliers from current price', () => {
    const result = calculateScenario(
      scenarioInputs({
        amountOfShares: [100, null, null, null, null],
        sharesChangePercent: [0, 0, 0, 0, 0],
        revenue: [1_000, null, null, null, null],
        revenueGrowthPercent: [0, 0, 0, 0, 0],
        priceToSales: [1, 1.5, 2, 2.5, 3],
      }),
      10,
    )

    expect(result.derived.sharePriceBasedOnPriceToSales).toEqual([
      10,
      15,
      20,
      25,
      30,
    ])
    expect(result.derived.sharePriceBasedOnPriceToSalesCagr[0]).toBeNull()
    expect(result.derived.sharePriceBasedOnPriceToSalesCagr[1]).toBeNull()
    expect(result.derived.sharePriceBasedOnPriceToSalesCagr[2]).toBeCloseTo(
      0.2599,
    )
    expect(result.derived.sharePriceBasedOnPriceToSalesCagr[3]).toBeCloseTo(
      0.2574,
    )
    expect(result.derived.sharePriceBasedOnPriceToSalesCagr[4]).toBeCloseTo(
      0.2457,
    )
    expect(result.multipliers.sharePriceBasedOnPriceToSales).toBe(2)
  })

  it('keeps missing required inputs blank instead of producing zero values', () => {
    const result = calculateScenario(
      scenarioInputs({
        amountOfShares: [100, null, null, null, null],
        sharesChangePercent: [0, 0, null, 0, 0],
        revenue: [0, null, null, null, null],
        revenueGrowthPercent: [0, 10, 10, 10, 10],
        netIncome: [100, null, null, null, null],
        netIncomeGrowthPercent: [0, null, 10, 10, 10],
        priceToSales: [2, 2, 2, 2, 2],
        peEstimateLow: [10, null, 10, 10, 10],
      }),
    )

    expect(result.derived.amountOfShares).toEqual([100, 100, null, null, null])
    expect(result.derived.netIncome).toEqual([100, null, null, null, null])
    expect(result.derived.netIncomeMargin).toEqual([null, null, null, null, null])
    expect(result.derived.sharePriceEstimateLow).toEqual([
      10,
      null,
      null,
      null,
      null,
    ])
    expect(result.derived.sharePriceBasedOnPriceToSales).toEqual([
      0,
      0,
      null,
      null,
      null,
    ])
  })

  it('coerces saved payloads into valuation models', () => {
    const model = stockAnalysisValuationModelFromPayload(
      {
        firstForecastYear: 2028,
        bull: {
          revenue: [100, 'bad', 120],
        },
        base: {},
        bear: null,
      },
      10,
    )

    expect(model.firstForecastYear).toBe(2028)
    expect(model.currentPrice).toBe(10)
    expect(model.scenarios.bull.revenue).toEqual([100, null, 120, null, null])
    expect(model.scenarios.base.revenue).toEqual([null, null, null, null, null])
    expect(model.scenarios.bear.revenue).toEqual([null, null, null, null, null])
  })

  it('keeps table metadata in the shared row registry', () => {
    expect(valuationRowMetadata('revenue')?.formatKind).toBe('dollar')
    expect(valuationRowMetadata('netIncomeMargin')?.formatKind).toBe(
      'ratioPercent',
    )
    expect(hasSpacerAfter('revenueGrowthPercent')).toBe(true)
    expect(hasSpacerAfter('netIncomeGrowthPercent')).toBe(false)
    expect(hasSpacerAfter('eps')).toBe(true)
    expect(isSharePriceRow('sharePriceEstimateLow')).toBe(true)
  })
})

function scenarioInputs(
  overrides: Partial<ScenarioEditableInputs>,
): ScenarioEditableInputs {
  return {
    ...createEmptyValuationModel().scenarios.base,
    ...overrides,
  }
}
