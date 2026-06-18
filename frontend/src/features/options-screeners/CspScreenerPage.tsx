import type { PortfolioResponse } from '@/api/portfolio'
import type { SingleLegColumn } from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  cspCandidates,
  type CspSortKey,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'
import {
  SingleLegScreenerPage,
  type SingleLegScreenerConfig,
} from '@/features/options-screeners/SingleLegScreenerPage'
import {
  formatScreenerPercentage,
  type CashSecuredPutCandidate,
} from '@/features/options-screeners/lib/screenerResults'
import { singleLegRefreshedContractWarning } from '@/features/options-screeners/lib/singleLegWarnings'

const discountColumn: SingleLegColumn<CashSecuredPutCandidate> = {
  key: 'discount_percentage',
  label: 'Discount %',
  render: (row) => formatScreenerPercentage(row.discount_percentage),
}

const config: SingleLegScreenerConfig<CashSecuredPutCandidate> = {
  title: 'Cash-Secured Put Screener',
  headingId: 'results-heading',
  right: 'PUT',
  invalidSortKey: 'gain_percentage',
  finalColumn: discountColumn,
  warning: (refreshed, _candidate, filters) =>
    singleLegRefreshedContractWarning({
      refreshed,
      filters,
      annualizedReturnDenominator: refreshed.strike,
      message: 'The refreshed contract no longer satisfies the current CSP scan filters.',
    }),
}

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
  const activeJob =
    state.activeJob?.screener === 'csp' ? state.activeJob : null
  return (
    <SingleLegScreenerPage
      config={config}
      activeJob={activeJob}
      snapshot={state.cspSnapshot}
      candidates={
        state.cspSnapshot ? cspCandidates(state.cspSnapshot.candidates) : []
      }
      filterDraft={state.cspFilterDraft}
      filterError={state.cspFilterError}
      filterSaveStatus={state.cspFilterSaveStatus}
      updateFilterDraft={state.updateCspFilterDraft}
      resetFilters={state.resetCspFilters}
      filters={state.cspFilters}
      sort={state.cspSort}
      setSort={(key) => state.setCspSort(key as CspSortKey)}
      startScan={state.startCspScan}
      portfolio={portfolio}
      selectedAccount={selectedAccount}
      onCandidateActivate={onCandidateActivate}
    />
  )
}
