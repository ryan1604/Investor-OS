import type { PortfolioResponse } from '@/api/portfolio'
import type { SingleLegColumn } from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  ccCandidates,
  type CcSortKey,
  cspCandidates,
  type CspSortKey,
  useOptionsScreeners,
} from '@/features/options-screeners/OptionsScreenersProvider'
import {
  SingleLegScreenerPage,
  type SingleLegScreenerConfig,
} from '@/features/options-screeners/SingleLegScreenerPage'
import {
  type CashSecuredPutCandidate,
  type CoveredCallCandidate,
  formatScreenerPercentage,
} from '@/features/options-screeners/lib/screenerResults'
import { singleLegRefreshedContractWarning } from '@/features/options-screeners/lib/singleLegWarnings'

type SharedProps<Candidate> = {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: Candidate) => void
}

type CspRouteProps = SharedProps<CashSecuredPutCandidate> & {
  kind: 'csp'
}

type CcRouteProps = SharedProps<CoveredCallCandidate> & {
  kind: 'cc'
}

const discountColumn: SingleLegColumn<CashSecuredPutCandidate> = {
  key: 'discount_percentage',
  label: 'Discount %',
  render: (row) => formatScreenerPercentage(row.discount_percentage),
}

const gainColumn: SingleLegColumn<CoveredCallCandidate> = {
  key: 'gain_percentage',
  label: 'Gain %',
  render: (row) => formatScreenerPercentage(row.gain_percentage),
}

const cspConfig: SingleLegScreenerConfig<CashSecuredPutCandidate> = {
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

const ccConfig: SingleLegScreenerConfig<CoveredCallCandidate> = {
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

export function SingleLegScreenerRoute(
  props: CspRouteProps | CcRouteProps,
) {
  const state = useOptionsScreeners()

  if (props.kind === 'csp') {
    return (
      <SingleLegScreenerPage
        config={cspConfig}
        activeJob={state.activeJob?.screener === 'csp' ? state.activeJob : null}
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
        portfolio={props.portfolio}
        selectedAccount={props.selectedAccount}
        onCandidateActivate={props.onCandidateActivate}
      />
    )
  }

  return (
    <SingleLegScreenerPage
      config={ccConfig}
      activeJob={state.activeJob?.screener === 'cc' ? state.activeJob : null}
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
      portfolio={props.portfolio}
      selectedAccount={props.selectedAccount}
      onCandidateActivate={props.onCandidateActivate}
    />
  )
}
