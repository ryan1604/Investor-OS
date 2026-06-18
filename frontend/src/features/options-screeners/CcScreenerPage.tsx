import type { PortfolioResponse } from '@/api/portfolio'
import type { SingleLegColumn } from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  ccCandidates,
  type CcSortKey,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'
import {
  SingleLegScreenerPage,
  type SingleLegScreenerConfig,
} from '@/features/options-screeners/SingleLegScreenerPage'
import {
  formatScreenerPercentage,
  type CoveredCallCandidate,
} from '@/features/options-screeners/lib/screenerResults'
import { singleLegRefreshedContractWarning } from '@/features/options-screeners/lib/singleLegWarnings'

const gainColumn: SingleLegColumn<CoveredCallCandidate> = {
  key: 'gain_percentage',
  label: 'Gain %',
  render: (row) => formatScreenerPercentage(row.gain_percentage),
}

const config: SingleLegScreenerConfig<CoveredCallCandidate> = {
  title: 'Covered Call Screener',
  headingId: 'cc-results-heading',
  right: 'CALL',
  invalidSortKey: 'discount_percentage',
  finalColumn: gainColumn,
  warning: (refreshed, candidate, filters) =>
    singleLegRefreshedContractWarning({
      refreshed,
      filters,
      annualizedReturnDenominator: candidate.stock_price,
      message: 'The refreshed contract no longer satisfies the current CC scan filters.',
    }),
}

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
  const activeJob =
    state.activeJob?.screener === 'cc' ? state.activeJob : null
  return (
    <SingleLegScreenerPage
      config={config}
      activeJob={activeJob}
      snapshot={state.ccSnapshot}
      candidates={
        state.ccSnapshot ? ccCandidates(state.ccSnapshot.candidates) : []
      }
      filterDraft={state.ccFilterDraft}
      filterError={state.ccFilterError}
      filterSaveStatus={state.ccFilterSaveStatus}
      updateFilterDraft={state.updateCcFilterDraft}
      resetFilters={state.resetCcFilters}
      filters={state.ccFilters}
      sort={state.ccSort}
      setSort={(key) => state.setCcSort(key as CcSortKey)}
      startScan={state.startCcScan}
      portfolio={portfolio}
      selectedAccount={selectedAccount}
      onCandidateActivate={onCandidateActivate}
    />
  )
}
