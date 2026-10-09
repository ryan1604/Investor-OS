import type { PortfolioResponse } from '@/api/portfolio'
import {
  refreshOptionsScreenerQuote,
  type OptionsScreenerFilters,
  type OptionsScreenerQuoteRefreshResponse,
  type ScreenerCandidate,
} from '@/api/optionsScreeners'
import { OptionStrategyTicket } from '@/features/orders/components/OptionStrategyTicket'
import { ScanActionButton } from '@/features/options-screeners/components/ScanActionButton'
import { ScreenerPageShell } from '@/features/options-screeners/components/ScreenerPageShell'
import {
  SingleLegResultsTable,
  type SingleLegCandidate,
  type SingleLegColumn,
  type SingleLegSortKey,
} from '@/features/options-screeners/components/SingleLegResultsTable'
import { ScreenerFilterControls } from '@/features/options-screeners/components/ScreenerFilterControls'
import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'
import { useScreenerTicketRefresh } from '@/features/options-screeners/hooks/useScreenerTicketRefresh'
import { useOptionsScreeners } from '@/features/options-screeners/hooks/useOptionsScreeners'
import { errorMessage } from '@/lib/errors'

export type SingleLegScreenerConfig<Candidate extends SingleLegCandidate> = {
  title: string
  headingId: string
  right: 'PUT' | 'CALL'
  selectCandidates: (candidates: ScreenerCandidate[]) => Candidate[]
  finalColumn: SingleLegColumn<Candidate>
  warning: (
    refreshed: OptionsScreenerQuoteRefreshResponse,
    candidate: Candidate,
    filters: OptionsScreenerFilters,
  ) => string | null
}

export function SingleLegScreenerPage<Candidate extends SingleLegCandidate>({
  screener,
  config,
  portfolio,
  selectedAccount,
}: {
  screener: 'csp' | 'cc'
  config: SingleLegScreenerConfig<Candidate>
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}) {
  const state = useOptionsScreeners()
  const slice = state.screeners[screener]
  const activeJob = state.activeJob?.screener === screener ? state.activeJob : null
  const candidates = slice.snapshot ? config.selectCandidates(slice.snapshot.candidates) : []
  const ticket = useScreenerTicketRefresh({
    refresh: refreshTicket,
    errorMessage: (error) => errorMessage(error, 'The selected option contract could not be refreshed.'),
  })
  const scanDisabled =
    !slice.tickers.length ||
    Boolean(slice.filterError) ||
    Boolean(state.activeJob) ||
    state.isLoading

  function setSort(key: SingleLegSortKey) {
    if (screener === 'csp' && key !== 'gain_percentage') {
      state.screeners.csp.setSort(key)
    } else if (screener === 'cc' && key !== 'discount_percentage') {
      state.screeners.cc.setSort(key)
    }
  }

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
      warning: config.warning(refreshed, candidate, slice.filters),
    }
  }

  return (
    <ScreenerPageShell
      title={config.title}
      loadError={state.loadError}
      scanActionError={state.scanActionError}
      headingId={config.headingId}
      activeJob={activeJob}
      snapshot={slice.snapshot}
      visibleCount={candidates.length}
      ticketError={ticket.ticketError}
      isRefreshingTicket={ticket.isRefreshingTicket}
      refreshMessage="Refreshing the selected contract and quote..."
      tickerEditor={
        <TickerListEditor
          tickers={slice.tickers}
          error={state.tickerSaveError}
          isPending={state.isTickerUpdatePending}
          onAdd={slice.addTickers}
          onRemove={slice.removeTicker}
          onClear={slice.clearTickers}
        />
      }
      filters={
        <ScreenerFilterControls
          draft={slice.filterDraft}
          error={slice.filterError}
          saveStatus={slice.filterSaveStatus}
          onChange={slice.updateFilterDraft}
          onReset={slice.resetFilters}
          action={
            <ScanActionButton
              activeJob={activeJob}
              disabled={scanDisabled}
              tickerCount={slice.tickers.length}
              onStartScan={slice.startScan}
              onCancelScan={state.cancelActiveScan}
            />
          }
        />
      }
      results={
        <SingleLegResultsTable
          candidates={candidates}
          emptyMessage={slice.snapshot ? 'No matching contracts' : 'Start a scan'}
          finalColumn={config.finalColumn}
          sort={slice.sort}
          onSort={setSort}
          onActivate={(candidate) => {
            void ticket.refreshTicket(candidate)
          }}
        />
      }
    >
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
    </ScreenerPageShell>
  )
}
