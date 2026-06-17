import { LoaderCircle, Radar, Square } from 'lucide-react'

import type { PortfolioResponse } from '@/api/portfolio'
import { refreshOptionsScreenerSpreadQuote } from '@/api/optionsScreeners'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { CsFilterControls } from '@/features/options-screeners/components/CsFilterControls'
import { CsResultsTable } from '@/features/options-screeners/components/CsResultsTable'
import { ScreenerResultsStatus } from '@/features/options-screeners/components/ScreenerResultsStatus'
import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'
import {
  csCandidates,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'
import type { CreditSpreadCandidate } from '@/features/options-screeners/lib/screenerResults'
import { useScreenerTicketRefresh } from '@/features/options-screeners/hooks/useScreenerTicketRefresh'
import { OptionStrategyTicket } from '@/features/options/components/OptionStrategyTicket'

export function CsScreenerPage({
  portfolio,
  selectedAccount,
  onCandidateActivate,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: CreditSpreadCandidate) => void
}) {
  const state = useOptionsScreeners()
  const ticket = useScreenerTicketRefresh({
    refresh: refreshTicket,
    errorMessage,
  })
  const activeCsJob =
    state.activeJob?.screener === 'cs' ? state.activeJob : null
  const snapshotCandidates = state.csSnapshot
    ? csCandidates(state.csSnapshot.candidates)
    : []
  const scanDisabled =
    !state.csTickers.length ||
    Boolean(state.csFilterError) ||
    Boolean(state.activeJob) ||
    state.isLoading

  async function refreshTicket(candidate: CreditSpreadCandidate) {
    const refreshed = await refreshOptionsScreenerSpreadQuote({
        strategy: candidate.strategy,
        ticker: candidate.ticker,
        expiration: candidate.expiration,
        short_strike: candidate.short_strike,
        long_strike: candidate.long_strike,
        short_contract: candidate.short_contract,
        long_contract: candidate.long_contract,
      })
    return {
      legs: [
        {
          ticker: refreshed.ticker,
          expiration: refreshed.expiration,
          right: refreshed.right,
          strike: refreshed.short_strike,
          signedQuantity: -1,
          quote: refreshed.short_midpoint,
          bid: refreshed.short_bid,
          ask: refreshed.short_ask,
        },
        {
          ticker: refreshed.ticker,
          expiration: refreshed.expiration,
          right: refreshed.right,
          strike: refreshed.long_strike,
          signedQuantity: 1,
          quote: refreshed.long_midpoint,
          bid: refreshed.long_bid,
          ask: refreshed.long_ask,
        },
      ],
      warning: refreshedCandidateWarning(refreshed, candidate, state.csFilters),
    }
  }

  return (
    <main className="w-full space-y-5">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Credit Spread Screener
        </h1>
      </header>

      {state.loadError ? <Alert variant="destructive">{state.loadError}</Alert> : null}
      {state.scanActionError ? (
        <Alert variant="destructive">{state.scanActionError}</Alert>
      ) : null}
      <Card className="pt-2">
        <CardContent className="space-y-6">
          <TickerListEditor
            tickers={state.csTickers}
            error={state.tickerSaveError}
            isPending={state.isTickerUpdatePending}
            clearTitle="Clear the CS ticker list?"
            clearDescription="This removes every saved ticker from the credit-spread screener only. Completed scan snapshots are not changed."
            clearActionLabel="Clear CS list"
            onAdd={state.addCsTickers}
            onRemove={state.removeCsTicker}
            onClear={state.clearCsTickers}
          />
          <CsFilterControls
            draft={state.csFilterDraft}
            error={state.csFilterError}
            saveStatus={state.csFilterSaveStatus}
            onChange={state.updateCsFilterDraft}
            onToggleStrategy={state.toggleCsStrategyType}
            onToggleWidth={state.toggleCsSpreadWidth}
            onReset={state.resetCsFilters}
            action={
              activeCsJob ? (
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
                  onClick={() => void state.startCsScan()}
                >
                  <Radar />
                  Scan {state.csTickers.length || ''} ticker
                  {state.csTickers.length === 1 ? '' : 's'}
                </Button>
              )
            }
          />
        </CardContent>
      </Card>

      <section className="space-y-3" aria-labelledby="cs-results-heading">
        <ScreenerResultsStatus
          activeJob={activeCsJob}
          snapshot={state.csSnapshot}
          visibleCount={snapshotCandidates.length}
          headingId="cs-results-heading"
        />
        {ticket.ticketError ? (
          <Alert variant="destructive">{ticket.ticketError}</Alert>
        ) : null}
        {ticket.isRefreshingTicket ? (
          <Alert className="flex items-center gap-2">
            <LoaderCircle className="size-4 shrink-0 animate-spin" />
            <span>Refreshing both spread legs and net credit...</span>
          </Alert>
        ) : null}
        <CsResultsTable
          candidates={snapshotCandidates}
          emptyMessage={
            state.csSnapshot ? 'No matching spreads' : 'Start a scan'
          }
          sort={state.csSort}
          onSort={state.setCsSort}
          onActivate={(candidate) => {
            onCandidateActivate?.(candidate)
            void ticket.refreshTicket(candidate)
          }}
        />
      </section>
      {ticket.ticketLegs.length ? (
        <OptionStrategyTicket
          key={`${ticket.ticketLegs[0].ticker}-${ticket.ticketLegs[0].expiration}-${ticket.ticketLegs[0].strike}-${ticket.ticketLegs[1]?.strike}`}
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
  refreshed: Awaited<ReturnType<typeof refreshOptionsScreenerSpreadQuote>>,
  candidate: CreditSpreadCandidate,
  filters: {
    minimum_dte: number
    maximum_dte: number
    minimum_absolute_delta: number
    maximum_absolute_delta: number
    minimum_annualized_return: number
  },
) {
  const refreshedDte = daysToExpiration(refreshed.expiration)
  const absoluteDelta =
    refreshed.short_delta === null ? null : Math.abs(refreshed.short_delta)
  const width = Math.abs(refreshed.short_strike - refreshed.long_strike)
  const expectedWidth = Math.abs(candidate.short_strike - candidate.long_strike)
  const annualizedReturn =
    refreshedDte > 0 && refreshed.maximum_loss > 0
      ? (refreshed.net_midpoint / refreshed.maximum_loss) *
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
    annualizedReturn >= filters.minimum_annualized_return &&
    Math.abs(width - expectedWidth) <= 1e-6 &&
    refreshed.net_midpoint > 0 &&
    refreshed.net_midpoint < width &&
    refreshed.maximum_loss > 0

  return matches
    ? null
    : 'The refreshed spread no longer satisfies the current CS scan filters, exact width, or maximum-loss rules.'
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
    : 'The selected credit spread could not be refreshed.'
}
