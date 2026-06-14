import {
  useCallback,
  useMemo,
  useState,
} from 'react'

import { LoaderCircle, Search, Tickets } from 'lucide-react'
import type { IChartApi } from 'lightweight-charts'

import type { OrderRecord } from '@/api/orders'
import type { PortfolioResponse } from '@/api/portfolio'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ExpirationTabs } from '@/features/options/components/ExpirationTabs'
import { OptionChainTable } from '@/features/options/components/OptionChainTable'
import { OptionStrategyTicket } from '@/features/options/components/OptionStrategyTicket'
import { OptionsChart } from '@/features/options/components/OptionsChart'
import { RsiChart } from '@/features/options/components/RsiChart'
import { StockTradeTicket } from '@/features/options/components/StockTradeTicket'
import { useOptionChain } from '@/features/options/hooks/useOptionChain'
import { useOptionsChartStream } from '@/features/options/hooks/useOptionsChartStream'
import { useSyncedChartRange } from '@/features/options/hooks/useSyncedChartRange'
import {
  hasAnalysisPriceData,
  useOptionsAnalysis,
} from '@/features/options/hooks/useOptionsAnalysis'
import {
  mergeOptionQuoteSelection,
  type DraftOptionLeg,
  type OptionQuoteSelection,
} from '@/features/options/lib/strategyLegs'
import { chartOverlays } from '@/features/options/lib/chartOverlays'

type OptionsPageProps = {
  orders: OrderRecord[]
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}

export function OptionsPage({
  orders,
  portfolio,
  selectedAccount,
}: OptionsPageProps) {
  const [priceChart, setPriceChart] = useState<IChartApi | null>(null)
  const [rsiChart, setRsiChart] = useState<IChartApi | null>(null)
  const [draftOptionLegs, setDraftOptionLegs] = useState<DraftOptionLeg[]>([])
  const [isStrategyTicketOpen, setIsStrategyTicketOpen] = useState(false)
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
  const overlays = useMemo(() => {
    if (!analysis) {
      return []
    }

    return chartOverlays({
      draftLegs: draftOptionLegs,
      orders,
      portfolio,
      selectedAccount,
      ticker: analysis.ticker,
    })
  }, [analysis, draftOptionLegs, orders, portfolio, selectedAccount])
  const handlePriceChartReady = useCallback((chart: IChartApi | null) => {
    setPriceChart(chart)
  }, [])
  const handleRsiChartReady = useCallback((chart: IChartApi | null) => {
    setRsiChart(chart)
  }, [])
  const handleDraftOptionLegsChange = useCallback((legs: DraftOptionLeg[]) => {
    setDraftOptionLegs(legs)
    if (!legs.length) {
      setIsStrategyTicketOpen(false)
    }
  }, [])
  const handleQuoteClick = useCallback((selection: OptionQuoteSelection) => {
    setDraftOptionLegs((currentLegs) => {
      const nextLegs = mergeOptionQuoteSelection(currentLegs, selection)
      if (!nextLegs.length) {
        setIsStrategyTicketOpen(false)
      }
      return nextLegs
    })
  }, [])

  useSyncedChartRange(priceChart, rsiChart)

  return (
    <main className="flex min-w-0 w-full flex-col gap-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Options
        </h1>

        <div className="flex w-full items-center gap-2 sm:max-w-xl sm:justify-end">
          <form
            className="flex min-w-0 flex-1 items-center gap-2 sm:max-w-sm"
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
                <LoaderCircle
                  className="animate-spin"
                  data-icon="inline-start"
                />
              ) : (
                <Search data-icon="inline-start" />
              )}
              Search
            </Button>
          </form>
          {analysis && hasAnalysisPriceData(analysis) ? (
            <>
              <Button
                type="button"
                variant="outline"
                disabled={!draftOptionLegs.length}
                onClick={() => setIsStrategyTicketOpen(true)}
                className="cursor-pointer active:cursor-pointer disabled:cursor-not-allowed"
              >
                <Tickets data-icon="inline-start" />
                Strategy
                {draftOptionLegs.length ? ` (${draftOptionLegs.length})` : ''}
              </Button>
              <StockTradeTicket
                ticker={analysis.ticker}
                latestPrice={analysis.underlying_price}
                portfolio={portfolio}
                selectedAccount={selectedAccount}
              />
            </>
          ) : null}
        </div>
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
                overlays={overlays}
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
                <ExpirationTabs
                  expirations={expirations}
                  selectedExpiration={selectedExpiration}
                  onSelectedExpirationChange={setSelectedExpiration}
                />
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
                  onQuoteClick={handleQuoteClick}
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
      {draftOptionLegs.length ? (
        <OptionStrategyTicket
          legs={draftOptionLegs}
          open={isStrategyTicketOpen}
          portfolio={portfolio}
          selectedAccount={selectedAccount}
          onLegsChange={handleDraftOptionLegsChange}
          onOpenChange={setIsStrategyTicketOpen}
        />
      ) : null}
    </main>
  )
}
