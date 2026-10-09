import type { PortfolioResponse } from '@/api/portfolio'
import type { SingleLegColumn } from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  SingleLegScreenerPage,
  type SingleLegScreenerConfig,
} from '@/features/options-screeners/SingleLegScreenerPage'
import type { CashSecuredPutCandidate, CoveredCallCandidate } from '@/api/optionsScreeners'
import {
  ccCandidates,
  cspCandidates,
  formatScreenerPercentage,
} from '@/features/options-screeners/lib/screenerResults'
import { singleLegRefreshedContractWarning } from '@/features/options-screeners/lib/singleLegWarnings'

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
  selectCandidates: cspCandidates,
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
  selectCandidates: ccCandidates,
  finalColumn: gainColumn,
  warning: (refreshed, candidate, filters) =>
    singleLegRefreshedContractWarning({
      refreshed,
      filters,
      annualizedReturnDenominator: candidate.stock_price,
      message: 'The refreshed contract no longer satisfies the current CC scan filters.',
    }),
}

export function SingleLegScreenerRoute({
  screener,
  portfolio,
  selectedAccount,
}: {
  screener: 'csp' | 'cc'
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}) {
  return screener === 'csp' ? (
    <SingleLegScreenerPage
      screener="csp"
      config={cspConfig}
      portfolio={portfolio}
      selectedAccount={selectedAccount}
    />
  ) : (
    <SingleLegScreenerPage
      screener="cc"
      config={ccConfig}
      portfolio={portfolio}
      selectedAccount={selectedAccount}
    />
  )
}
