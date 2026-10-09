import type { PortfolioResponse } from '@/api/portfolio'
import { refreshOptionsScreenerSpreadQuote, type CreditSpreadCandidate } from '@/api/optionsScreeners'
import { OptionStrategyTicket } from '@/features/orders/components/OptionStrategyTicket'
import { CsFilterControls } from '@/features/options-screeners/components/CsFilterControls'
import { CsResultsTable } from '@/features/options-screeners/components/CsResultsTable'
import { ScanActionButton } from '@/features/options-screeners/components/ScanActionButton'
import { ScreenerPageShell } from '@/features/options-screeners/components/ScreenerPageShell'
import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'
import { useOptionsScreeners } from '@/features/options-screeners/hooks/useOptionsScreeners'
import { csCandidates } from '@/features/options-screeners/lib/screenerResults'
import { refreshedCandidateWarning } from '@/features/options-screeners/lib/refreshedCandidateWarning'
import { useScreenerTicketRefresh } from '@/features/options-screeners/hooks/useScreenerTicketRefresh'
import { errorMessage } from '@/lib/errors'

export function CsScreenerPage({
  portfolio,
  selectedAccount,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}) {
  const state = useOptionsScreeners()
  const slice = state.screeners.cs
  const ticket = useScreenerTicketRefresh({
    refresh: refreshTicket,
    errorMessage: (error) => errorMessage(error, 'The selected credit spread could not be refreshed.'),
  })
  const activeCsJob = state.activeJob?.screener === 'cs' ? state.activeJob : null
  const snapshotCandidates = slice.snapshot ? csCandidates(slice.snapshot.candidates) : []
  const scanDisabled =
    !slice.tickers.length ||
    Boolean(slice.filterError) ||
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
      warning: refreshedCandidateWarning(refreshed, candidate, slice.filters),
    }
  }

  return (
    <ScreenerPageShell
      title="Credit Spread Screener"
      loadError={state.loadError}
      scanActionError={state.scanActionError}
      headingId="cs-results-heading"
      activeJob={activeCsJob}
      snapshot={slice.snapshot}
      visibleCount={snapshotCandidates.length}
      ticketError={ticket.ticketError}
      isRefreshingTicket={ticket.isRefreshingTicket}
      refreshMessage="Refreshing both spread legs and net credit..."
      tickerEditor={
        <TickerListEditor
          tickers={slice.tickers}
          error={state.tickerSaveError}
          isPending={state.isTickerUpdatePending}
          clearTitle="Clear the CS ticker list?"
          clearDescription="This removes every saved ticker from the credit-spread screener only. Completed scan snapshots are not changed."
          clearActionLabel="Clear CS list"
          onAdd={slice.addTickers}
          onRemove={slice.removeTicker}
          onClear={slice.clearTickers}
        />
      }
      filters={
        <CsFilterControls
          draft={slice.filterDraft}
          error={slice.filterError}
          saveStatus={slice.filterSaveStatus}
          onChange={slice.updateFilterDraft}
          onToggleStrategy={slice.toggleStrategyType}
          onToggleWidth={slice.toggleSpreadWidth}
          onReset={slice.resetFilters}
          action={
            <ScanActionButton
              activeJob={activeCsJob}
              disabled={scanDisabled}
              tickerCount={slice.tickers.length}
              onStartScan={slice.startScan}
              onCancelScan={state.cancelActiveScan}
            />
          }
        />
      }
      results={
        <CsResultsTable
          candidates={snapshotCandidates}
          emptyMessage={slice.snapshot ? 'No matching spreads' : 'Start a scan'}
          sort={slice.sort}
          onSort={slice.setSort}
          onActivate={(candidate) => {
            void ticket.refreshTicket(candidate)
          }}
        />
      }
    >
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
    </ScreenerPageShell>
  )
}
