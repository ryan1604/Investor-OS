import type { PortfolioResponse } from '@/api/portfolio'
import { SingleLegScreenerRoute } from '@/features/options-screeners/SingleLegScreenerRoute'
import type { CashSecuredPutCandidate } from '@/features/options-screeners/lib/screenerResults'

export function CspScreenerPage({
  portfolio,
  selectedAccount,
  onCandidateActivate,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: CashSecuredPutCandidate) => void
}) {
  return (
    <SingleLegScreenerRoute
      kind="csp"
      portfolio={portfolio}
      selectedAccount={selectedAccount}
      onCandidateActivate={onCandidateActivate}
    />
  )
}
