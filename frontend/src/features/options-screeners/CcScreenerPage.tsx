import { LoaderCircle, Radar, Square } from 'lucide-react'

import type { PortfolioResponse } from '@/api/portfolio'
import { refreshOptionsScreenerQuote } from '@/api/optionsScreeners'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { CcResultsTable } from '@/features/options-screeners/components/CcResultsTable'
import { ScreenerFilterControls } from '@/features/options-screeners/components/ScreenerFilterControls'
import { ScreenerResultsStatus } from '@/features/options-screeners/components/ScreenerResultsStatus'
import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'
import {
  ccCandidates,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'
import type { CoveredCallCandidate } from '@/features/options-screeners/lib/screenerResults'
import { useScreenerTicketRefresh } from '@/features/options-screeners/hooks/useScreenerTicketRefresh'
import { OptionStrategyTicket } from '@/features/options/components/OptionStrategyTicket'

export function CcScreenerPage({
  portfolio,
  selectedAccount,
  onCandidateActivate,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: CoveredCallCandidate) => void
}) {
  const state = useOptionsScreeners()
  const ticket = useScreenerTicketRefresh({
    refresh: refreshTicket,
    errorMessage,
  })
  const activeCcJob =
    state.activeJob?.screener === 'cc' ? state.activeJob : null
  const snapshotCandidates = state.ccSnapshot
    ? ccCandidates(state.ccSnapshot.candidates)
    : []
  const scanDisabled =
    !state.cspTickers.length ||
    Boolean(state.ccFilterError) ||
    Boolean(state.activeJob) ||
    state.isLoading

  async function refreshTicket(candidate: CoveredCallCandidate) {
    const refreshed = await refreshOptionsScreenerQuote({
        ticker: candidate.ticker,
        expiration: candidate.expiration,
        strike: candidate.strike,
        right: 'CALL',
        contract: candidate.contract,
      })
    return {
      legs: [
        {
          ticker: refreshed.ticker,
          expiration: refreshed.expiration,
          right: refreshed.right,
          strike: refreshed.strike,
          signedQuantity: -1,
          quote: refreshed.midpoint,
          bid: refreshed.bid,
          ask: refreshed.ask,
        },
      ],
      warning: refreshedCandidateWarning(
        refreshed,
        candidate.stock_price,
        state.ccFilters,
      ),
    }
  }

  return (
    <main className="w-full space-y-5">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Covered Call Screener
        </h1>
      </header>

      {state.loadError ? <Alert variant="destructive">{state.loadError}</Alert> : null}
      {state.scanActionError ? (
        <Alert variant="destructive">{state.scanActionError}</Alert>
      ) : null}
      <Card className="pt-2">
        <CardContent className="space-y-6">
          <TickerListEditor
            tickers={state.cspTickers}
            error={state.tickerSaveError}
            isPending={state.isTickerUpdatePending}
            onAdd={state.addCspTickers}
            onRemove={state.removeCspTicker}
            onClear={state.clearCspTickers}
          />
          <ScreenerFilterControls
            draft={state.ccFilterDraft}
            error={state.ccFilterError}
            saveStatus={state.ccFilterSaveStatus}
            onChange={state.updateCcFilterDraft}
            onReset={state.resetCcFilters}
            action={
              activeCcJob ? (
                <Button
                  variant="destructive"
                  className="cursor-pointer"
                  onClick={() => void state.cancelActiveScan()}
                >
                  <Square className="fill-current" />
                  Cancel scan
                </Button>
              ) : (
                <Button
                  className="cursor-pointer disabled:cursor-not-allowed"
                  disabled={scanDisabled}
                  onClick={() => void state.startCcScan()}
                >
                  <Radar />
                  Scan {state.cspTickers.length || ''} ticker
                  {state.cspTickers.length === 1 ? '' : 's'}
                </Button>
              )
            }
          />
        </CardContent>
      </Card>

      <section className="space-y-3" aria-labelledby="cc-results-heading">
        <ScreenerResultsStatus
          activeJob={activeCcJob}
          snapshot={state.ccSnapshot}
          visibleCount={snapshotCandidates.length}
          headingId="cc-results-heading"
        />
        {ticket.ticketError ? (
          <Alert variant="destructive">{ticket.ticketError}</Alert>
        ) : null}
        {ticket.isRefreshingTicket ? (
          <Alert className="flex items-center gap-2">
            <LoaderCircle className="size-4 shrink-0 animate-spin" />
            <span>Refreshing the selected contract and quote...</span>
          </Alert>
        ) : null}
        <CcResultsTable
          candidates={snapshotCandidates}
          emptyMessage={
            state.ccSnapshot ? 'No matching contracts' : 'Start a scan'
          }
          sort={state.ccSort}
          onSort={state.setCcSort}
          onActivate={(candidate) => {
            onCandidateActivate?.(candidate)
            void ticket.refreshTicket(candidate)
          }}
        />
      </section>
      {ticket.ticketLegs.length ? (
        <OptionStrategyTicket
          key={`${ticket.ticketLegs[0].ticker}-${ticket.ticketLegs[0].expiration}-${ticket.ticketLegs[0].strike}`}
          legs={ticket.ticketLegs}
          open={ticket.isTicketOpen}
          portfolio={portfolio}
          selectedAccount={selectedAccount}
          creditEntry
          selectedAccountOnly
          warning={ticket.ticketWarning}
          onLegsChange={ticket.setTicketLegs}
          onOpenChange={ticket.setIsTicketOpen}
        />
      ) : null}
    </main>
  )
}

function refreshedCandidateWarning(
  refreshed: Awaited<ReturnType<typeof refreshOptionsScreenerQuote>>,
  stockPrice: number,
  filters: {
    minimum_dte: number
    maximum_dte: number
    minimum_absolute_delta: number
    maximum_absolute_delta: number
    minimum_annualized_return: number
  },
) {
  const absoluteDelta = refreshed.delta === null ? null : Math.abs(refreshed.delta)
  const refreshedDte = daysToExpiration(refreshed.expiration)
  const annualizedReturn =
    refreshedDte > 0 &&
    refreshed.midpoint > 0 &&
    stockPrice > 0
      ? (refreshed.midpoint / stockPrice) *
        (365 / refreshedDte) *
        100
      : null
  const matches =
    refreshedDte >= filters.minimum_dte &&
    refreshedDte <= filters.maximum_dte &&
    absoluteDelta !== null &&
    absoluteDelta >= filters.minimum_absolute_delta &&
    absoluteDelta <= filters.maximum_absolute_delta &&
    annualizedReturn !== null &&
    annualizedReturn >= filters.minimum_annualized_return

  return matches
    ? null
    : 'The refreshed contract no longer satisfies the current CC scan filters.'
}

function daysToExpiration(expiration: string) {
  const expirationTime = Date.parse(`${expiration}T00:00:00Z`)
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const datePart = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? ''
  const currentTime = Date.parse(
    `${datePart('year')}-${datePart('month')}-${datePart('day')}T00:00:00Z`,
  )
  return Math.round((expirationTime - currentTime) / 86_400_000)
}

function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : 'The selected option contract could not be refreshed.'
}
