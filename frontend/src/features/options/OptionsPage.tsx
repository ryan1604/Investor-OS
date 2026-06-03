import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type WheelEvent,
} from 'react'

import { LoaderCircle, Search } from 'lucide-react'
import type { IChartApi, LogicalRange } from 'lightweight-charts'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { OptionChainTable } from '@/features/options/components/OptionChainTable'
import { OptionsChart } from '@/features/options/components/OptionsChart'
import { RsiChart } from '@/features/options/components/RsiChart'
import { useOptionChain } from '@/features/options/hooks/useOptionChain'
import { useOptionsChartStream } from '@/features/options/hooks/useOptionsChartStream'
import {
  hasAnalysisPriceData,
  useOptionsAnalysis,
} from '@/features/options/hooks/useOptionsAnalysis'

export function OptionsPage() {
  const expirationsListRef = useRef<HTMLDivElement | null>(null)
  const [priceChart, setPriceChart] = useState<IChartApi | null>(null)
  const [rsiChart, setRsiChart] = useState<IChartApi | null>(null)
  const {
    analysis: initialAnalysis,
    error,
    expirations,
    expirationsError,
    handleSubmit,
    isExpirationsLoading,
    isLoading,
    selectedExpiration,
    setSelectedExpiration,
    setTicker,
    ticker,
  } = useOptionsAnalysis()
  const {
    analysis,
    error: chartStreamError,
    latestUpdate: latestChartUpdate,
  } = useOptionsChartStream(initialAnalysis)
  const { chain, chainError, isChainLoading } = useOptionChain(
    analysis,
    selectedExpiration,
    isLoading,
  )
  const handlePriceChartReady = useCallback((chart: IChartApi | null) => {
    setPriceChart(chart)
  }, [])
  const handleRsiChartReady = useCallback((chart: IChartApi | null) => {
    setRsiChart(chart)
  }, [])
  const handleExpirationWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      const expirationsList = expirationsListRef.current

      if (!expirationsList) {
        return
      }

      const maxScrollLeft =
        expirationsList.scrollWidth - expirationsList.clientWidth

      if (maxScrollLeft <= 0) {
        return
      }

      event.preventDefault()
      expirationsList.scrollLeft += event.deltaY || event.deltaX
    },
    [],
  )

  useEffect(() => {
    if (!priceChart || !rsiChart) {
      return
    }

    let isSyncing = false
    const syncRange = (targetChart: IChartApi, range: LogicalRange | null) => {
      if (isSyncing || !range) {
        return
      }

      isSyncing = true
      targetChart.timeScale().setVisibleLogicalRange(range)
      isSyncing = false
    }
    const syncRsiToPrice = (range: LogicalRange | null) => {
      syncRange(rsiChart, range)
    }
    const syncPriceToRsi = (range: LogicalRange | null) => {
      syncRange(priceChart, range)
    }

    priceChart.timeScale().subscribeVisibleLogicalRangeChange(syncRsiToPrice)
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange(syncPriceToRsi)

    const currentPriceRange = priceChart.timeScale().getVisibleLogicalRange()
    if (currentPriceRange) {
      rsiChart.timeScale().setVisibleLogicalRange(currentPriceRange)
    }

    return () => {
      priceChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncRsiToPrice)
      rsiChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncPriceToRsi)
    }
  }, [priceChart, rsiChart])

  return (
    <main className="flex min-w-0 w-full flex-col gap-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Options
        </h1>

        <form
          className="flex w-full items-center gap-2 sm:max-w-sm"
          onSubmit={handleSubmit}
        >
          <Input
            aria-label="Ticker"
            autoCapitalize="characters"
            autoComplete="off"
            className="h-9 uppercase"
            disabled={isLoading}
            maxLength={12}
            placeholder="AAPL"
            value={ticker}
            onChange={(event) => setTicker(event.target.value.toUpperCase())}
          />
          <Button
            type="submit"
            className="cursor-pointer active:cursor-pointer"
            disabled={isLoading}
          >
            {isLoading ? (
              <LoaderCircle className="animate-spin" data-icon="inline-start" />
            ) : (
              <Search data-icon="inline-start" />
            )}
            Search
          </Button>
        </form>
      </header>

      {error ? (
        <Alert variant="destructive">
          {error}
        </Alert>
      ) : null}

      {analysis ? (
        <div className="flex min-w-0 flex-col gap-4">
          {hasAnalysisPriceData(analysis) ? (
            <>
              <OptionsChart
                analysis={initialAnalysis ?? analysis}
                latestUpdate={latestChartUpdate}
                onChartReady={handlePriceChartReady}
              />
              <RsiChart
                analysis={initialAnalysis ?? analysis}
                latestUpdate={latestChartUpdate}
                onChartReady={handleRsiChartReady}
              />
              {chartStreamError ? (
                <Alert>{chartStreamError} Showing the latest available chart.</Alert>
              ) : null}
              {isExpirationsLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <LoaderCircle className="size-4 animate-spin" />
                  Loading expirations...
                </div>
              ) : null}
              {expirationsError ? (
                <Alert variant="destructive">{expirationsError}</Alert>
              ) : null}
              {expirations.length ? (
                <Tabs
                  value={selectedExpiration}
                  onValueChange={setSelectedExpiration}
                  className="min-w-0"
                >
                  <TabsList
                    ref={expirationsListRef}
                    className="no-scrollbar max-w-full justify-start overflow-x-auto overscroll-x-contain"
                    onWheel={handleExpirationWheel}
                  >
                    {expirations.map((expiration) => (
                      <TabsTrigger
                        key={expiration.date}
                        value={expiration.date}
                        className="cursor-pointer active:cursor-pointer"
                      >
                        {expiration.date}
                        {expiration.days_to_expiration !== null
                          ? ` (${expiration.days_to_expiration}D)`
                          : ''}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
              ) : null}
              {!isExpirationsLoading &&
              !expirationsError &&
              !expirations.length ? (
                <Alert>No option expirations were returned for {analysis.ticker}.</Alert>
              ) : null}
              {selectedExpiration ? (
                <OptionChainTable
                  analysis={analysis}
                  chain={chain}
                  error={chainError}
                  isLoading={isChainLoading}
                  selectedExpiration={selectedExpiration}
                />
              ) : null}
            </>
          ) : (
            <Alert>
              No daily price data was returned for {analysis.ticker}. The chart
              and option chain need an underlying price before they can load.
            </Alert>
          )}
        </div>
      ) : null}
    </main>
  )
}
