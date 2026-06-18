import { LoaderCircle, Radar, Square } from 'lucide-react'

import type { PortfolioResponse } from '@/api/portfolio'
import {
  refreshOptionsScreenerQuote,
  type OptionsScreenerFilters,
  type OptionsScreenerQuoteRefreshResponse,
} from '@/api/optionsScreeners'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  SingleLegResultsTable,
  type SingleLegCandidate,
  type SingleLegColumn,
  type SingleLegSortKey,
} from '@/features/options-screeners/components/SingleLegResultsTable'
import { ScreenerFilterControls } from '@/features/options-screeners/components/ScreenerFilterControls'
import { ScreenerResultsStatus } from '@/features/options-screeners/components/ScreenerResultsStatus'
import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'
import { useScreenerTicketRefresh } from '@/features/options-screeners/hooks/useScreenerTicketRefresh'
import { useOptionsScreeners } from '@/features/options-screeners/OptionsScreenersProvider'
import type { ScreenerFilterDraft } from '@/features/options-screeners/lib/screenerSettings'
import { OptionStrategyTicket } from '@/features/options/components/OptionStrategyTicket'

export type SingleLegScreenerConfig<Candidate extends SingleLegCandidate> = {
  title: string
  headingId: string
  right: 'PUT' | 'CALL'
  invalidSortKey: SingleLegSortKey
  finalColumn: SingleLegColumn<Candidate>
  warning: (
    refreshed: OptionsScreenerQuoteRefreshResponse,
    candidate: Candidate,
    filters: OptionsScreenerFilters,
  ) => string | null
}

export function SingleLegScreenerPage<Candidate extends SingleLegCandidate>({
  config,
  activeJob,
  snapshot,
  candidates,
  filterDraft,
  filterError,
  filterSaveStatus,
  updateFilterDraft,
  resetFilters,
  filters,
  sort,
  setSort,
  startScan,
  portfolio,
  selectedAccount,
  onCandidateActivate,
}: {
  config: SingleLegScreenerConfig<Candidate>
  activeJob: ReturnType<typeof useOptionsScreeners>['activeJob']
  snapshot: ReturnType<typeof useOptionsScreeners>['cspSnapshot']
  candidates: Candidate[]
  filterDraft: ScreenerFilterDraft
  filterError: string | null
  filterSaveStatus: ReturnType<typeof useOptionsScreeners>['cspFilterSaveStatus']
  updateFilterDraft: ReturnType<
    typeof useOptionsScreeners
  >['updateCspFilterDraft']
  resetFilters: () => void
  filters: OptionsScreenerFilters
  sort: {
    key: SingleLegSortKey
    direction: 'asc' | 'desc'
  }
  setSort: (key: SingleLegSortKey) => void
  startScan: () => Promise<void>
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: Candidate) => void
}) {
  const state = useOptionsScreeners()
  const ticket = useScreenerTicketRefresh({
    refresh: refreshTicket,
    errorMessage,
  })
  const scanDisabled =
    !state.cspTickers.length ||
    Boolean(filterError) ||
    Boolean(state.activeJob) ||
    state.isLoading

  async function refreshTicket(candidate: Candidate) {
    const refreshed = await refreshOptionsScreenerQuote({
      ticker: candidate.ticker,
      expiration: candidate.expiration,
      strike: candidate.strike,
      right: config.right,
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
      warning: config.warning(refreshed, candidate, filters),
    }
  }

  return (
    <main className="w-full space-y-5">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          {config.title}
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
            draft={filterDraft}
            error={filterError}
            saveStatus={filterSaveStatus}
            onChange={updateFilterDraft}
            onReset={resetFilters}
            action={
              activeJob ? (
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
                  onClick={() => void startScan()}
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

      <section className="space-y-3" aria-labelledby={config.headingId}>
        <ScreenerResultsStatus
          activeJob={activeJob}
          snapshot={snapshot}
          visibleCount={candidates.length}
          headingId={config.headingId}
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
        <SingleLegResultsTable
          candidates={candidates}
          emptyMessage={snapshot ? 'No matching contracts' : 'Start a scan'}
          finalColumn={config.finalColumn}
          sort={sort}
          onSort={(key) => {
            if (key !== config.invalidSortKey) {
              setSort(key)
            }
          }}
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

function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : 'The selected option contract could not be refreshed.'
}
