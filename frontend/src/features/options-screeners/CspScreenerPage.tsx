import { LoaderCircle, Radar, Square } from 'lucide-react'

import type { PortfolioResponse } from '@/api/portfolio'
import { refreshOptionsScreenerQuote } from '@/api/optionsScreeners'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { CspResultsTable } from '@/features/options-screeners/components/CspResultsTable'
import { ScreenerFilterControls } from '@/features/options-screeners/components/ScreenerFilterControls'
import { ScreenerResultsStatus } from '@/features/options-screeners/components/ScreenerResultsStatus'
import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'
import {
  cspCandidates,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'
import type { CashSecuredPutCandidate } from '@/features/options-screeners/lib/screenerResults'
import { useScreenerTicketRefresh } from '@/features/options-screeners/hooks/useScreenerTicketRefresh'
import { OptionStrategyTicket } from '@/features/options/components/OptionStrategyTicket'

export function CspScreenerPage({
  portfolio,
  selectedAccount,
  onCandidateActivate,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: CashSecuredPutCandidate) => void
}) {
  const state = useOptionsScreeners()
  const ticket = useScreenerTicketRefresh({
    refresh: refreshTicket,
    errorMessage,
  })
  const activeCspJob =
    state.activeJob?.screener === 'csp' ? state.activeJob : null
  const snapshotCandidates = state.cspSnapshot
    ? cspCandidates(state.cspSnapshot.candidates)
    : []
  const filtersInvalid = Boolean(state.cspFilterError)
  const scanDisabled =
    !state.cspTickers.length ||
    filtersInvalid ||
    Boolean(state.activeJob) ||
    state.isLoading

  async function refreshTicket(candidate: CashSecuredPutCandidate) {
    const refreshed = await refreshOptionsScreenerQuote({
        ticker: candidate.ticker,
        expiration: candidate.expiration,
        strike: candidate.strike,
        right: 'PUT',
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
      warning: refreshedCandidateWarning(refreshed, state.cspFilters),
    }
  }

  return (
    <main className="w-full space-y-5">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Cash-Secured Put Screener
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
            draft={state.cspFilterDraft}
            error={state.cspFilterError}
            saveStatus={state.cspFilterSaveStatus}
            onChange={state.updateCspFilterDraft}
            onReset={state.resetCspFilters}
            action={
              activeCspJob ? (
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
                  onClick={() => void state.startCspScan()}
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

      <section className="space-y-3" aria-labelledby="results-heading">
        <ScreenerResultsStatus
          activeJob={activeCspJob}
          snapshot={state.cspSnapshot}
          visibleCount={snapshotCandidates.length}
          headingId="results-heading"
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
        <CspResultsTable
          candidates={snapshotCandidates}
          emptyMessage={
            state.cspSnapshot ? 'No matching contracts' : 'Start a scan'
          }
          sort={state.cspSort}
          onSort={state.setCspSort}
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
    refreshed.strike > 0
      ? (refreshed.midpoint / refreshed.strike) *
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
    : 'The refreshed contract no longer satisfies the current CSP scan filters.'
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
