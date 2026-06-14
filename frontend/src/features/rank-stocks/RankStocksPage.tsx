import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  fetchStockAnalysisModels,
  refreshStockAnalysisCurrentPrices,
  type StockAnalysisModel,
  type StockAnalysisPriceRefreshResult,
} from '@/api/stockAnalysis'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  SCENARIO_KEYS,
  calculateValuationModel,
  stockAnalysisValuationModelFromPayload,
  type ScenarioKey,
  type SharePriceRowKey,
} from '@/features/stock-analysis/lib/valuationModel'

const REFRESH_INTERVAL_MS = 15 * 60 * 1000

const METRICS: {
  key: SharePriceRowKey
  label: string
}[] = [
  { key: 'sharePriceBasedOnPriceToSales', label: 'P/S' },
  { key: 'sharePriceEstimateLow', label: 'P/E' },
  { key: 'sharePriceBasedOnPriceToEbitda', label: 'P/EBITDA' },
  { key: 'sharePriceBasedOnPriceToOperatingCashFlow', label: 'P/OCF' },
  { key: 'sharePriceBasedOnPriceToFreeCashFlow', label: 'P/FCF' },
]

const SCENARIO_LABELS: Record<ScenarioKey, string> = {
  bull: 'Bull',
  base: 'Base',
  bear: 'Bear',
}

type RefreshStatus = 'idle' | 'refreshing' | 'complete' | 'error'

type RankingRow = {
  ticker: string
  returnPercent: number | null
}

export function RankStocksPage() {
  const [models, setModels] = useState<StockAnalysisModel[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus>('idle')
  const [refreshResults, setRefreshResults] = useState<
    StockAnalysisPriceRefreshResult[]
  >([])
  const [error, setError] = useState<string | null>(null)
  const refreshControllerRef = useRef<AbortController | null>(null)
  const refreshGenerationRef = useRef(0)

  const refreshPrices = useCallback(async () => {
    refreshControllerRef.current?.abort()
    const refreshController = new AbortController()
    refreshControllerRef.current = refreshController
    const refreshGeneration = ++refreshGenerationRef.current
    setRefreshStatus('refreshing')
    setError(null)
    try {
      const response = await refreshStockAnalysisCurrentPrices(
        refreshController.signal,
      )
      if (refreshGenerationRef.current !== refreshGeneration) {
        return
      }

      setRefreshResults(response.results)
      setModels((currentModels) =>
        mergeRefreshResults(currentModels, response.results),
      )
      setRefreshStatus('complete')
      setError(null)
    } catch (requestError) {
      if (
        isAbortError(requestError) ||
        refreshGenerationRef.current !== refreshGeneration
      ) {
        return
      }

      setRefreshStatus('error')
      setError(errorMessage(requestError))
    } finally {
      if (refreshControllerRef.current === refreshController) {
        refreshControllerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    const loadController = new AbortController()

    async function loadModels() {
      setIsLoading(true)
      setError(null)
      try {
        const savedModels = await fetchStockAnalysisModels(loadController.signal)
        setModels(savedModels)
        setIsLoading(false)
        void refreshPrices()
      } catch (requestError) {
        if (isAbortError(requestError)) {
          return
        }

        setIsLoading(false)
        setError(errorMessage(requestError))
      }
    }

    void loadModels()
    const refreshTimer = window.setInterval(() => {
      void refreshPrices()
    }, REFRESH_INTERVAL_MS)

    return () => {
      loadController.abort()
      refreshGenerationRef.current += 1
      refreshControllerRef.current?.abort()
      refreshControllerRef.current = null
      window.clearInterval(refreshTimer)
    }
  }, [refreshPrices])

  const rankings = useMemo(() => buildRankings(models), [models])
  const staleCount = refreshResults.filter(
    (result) => result.status === 'stale' || result.status === 'failed',
  ).length
  const missingCount = refreshResults.filter(
    (result) => result.status === 'missing',
  ).length

  return (
    <main className="flex min-w-0 w-full flex-col gap-5">
      <header className="flex flex-col gap-3 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="grid gap-1">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">
            Rank Stocks
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="outline">{models.length} tickers</Badge>
            <RefreshBadge status={refreshStatus} />
            {staleCount > 0 ? (
              <Badge variant="secondary">{staleCount} stale</Badge>
            ) : null}
            {missingCount > 0 ? (
              <Badge variant="outline">{missingCount} missing price</Badge>
            ) : null}
          </div>
        </div>
        <Button
          className="w-fit cursor-pointer active:cursor-pointer"
          disabled={isLoading || refreshStatus === 'refreshing'}
          variant="outline"
          onClick={() => void refreshPrices()}
        >
          <RefreshCw data-icon="inline-start" />
          Refresh
        </Button>
      </header>

      {error ? <Alert variant="destructive">{error}</Alert> : null}

      {isLoading ? (
        <div className="text-sm text-muted-foreground" role="status">
          Loading rankings...
        </div>
      ) : models.length === 0 ? (
        <section className="grid min-h-56 place-items-center rounded-lg border border-dashed bg-muted/20 p-8 text-center">
          <div className="grid gap-1">
            <h2 className="text-base font-semibold">No saved models</h2>
            <p className="text-sm text-muted-foreground">
              Saved Stock Analysis tickers will appear here.
            </p>
          </div>
        </section>
      ) : (
        <div className="grid gap-6">
          {SCENARIO_KEYS.map((scenario) => (
            <section className="grid gap-3" key={scenario}>
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold tracking-tight">
                  {SCENARIO_LABELS[scenario]}
                </h2>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                {METRICS.map((metric) => (
                  <RankingTable
                    key={metric.key}
                    label={metric.label}
                    rows={rankings[scenario][metric.key]}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </main>
  )
}

function RankingTable({ label, rows }: { label: string; rows: RankingRow[] }) {
  return (
    <section className="min-w-0 overflow-hidden rounded-lg border bg-background">
      <div className="border-b bg-muted/25 px-3 py-2">
        <h3 className="text-sm font-semibold">{label}</h3>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 px-3 text-xs">Ticker</TableHead>
            <TableHead className="h-8 px-3 text-right text-xs">Return %</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.ticker}>
              <TableCell className="px-3 py-1.5 font-medium">
                {row.ticker}
              </TableCell>
              <TableCell className="px-3 py-1.5 text-right tabular-nums">
                {formatReturnPercent(row.returnPercent)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  )
}

function RefreshBadge({ status }: { status: RefreshStatus }) {
  if (status === 'refreshing') {
    return <Badge variant="secondary">Refreshing</Badge>
  }

  if (status === 'complete') {
    return <Badge variant="secondary">Prices updated</Badge>
  }

  if (status === 'error') {
    return <Badge variant="destructive">Refresh failed</Badge>
  }

  return null
}

function buildRankings(models: StockAnalysisModel[]) {
  return Object.fromEntries(
    SCENARIO_KEYS.map((scenario) => [
      scenario,
      Object.fromEntries(
        METRICS.map((metric) => [
          metric.key,
          models
            .map((model) => rankingRow(model, scenario, metric.key))
            .sort(compareRankingRows),
        ]),
      ),
    ]),
  ) as Record<ScenarioKey, Record<SharePriceRowKey, RankingRow[]>>
}

function rankingRow(
  model: StockAnalysisModel,
  scenario: ScenarioKey,
  metric: SharePriceRowKey,
): RankingRow {
  const valuationModel = stockAnalysisValuationModelFromPayload(
    model.payload,
    model.current_price,
  )
  const calculatedModel = calculateValuationModel(valuationModel)

  return {
    ticker: model.ticker,
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

function mergeRefreshResults(
  models: StockAnalysisModel[],
  results: StockAnalysisPriceRefreshResult[],
) {
  const pricesByTicker = new Map(
    results
      .filter((result) => result.status === 'refreshed')
      .map((result) => [result.ticker, result.current_price]),
  )

  return models.map((model) =>
    pricesByTicker.has(model.ticker)
      ? {
          ...model,
          current_price: pricesByTicker.get(model.ticker) ?? null,
        }
      : model,
  )
}

function formatReturnPercent(value: number | null) {
  if (value === null) {
    return '-'
  }

  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    signDisplay: 'exceptZero',
    style: 'percent',
  }).format(value)
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Rank stocks request failed.'
}
