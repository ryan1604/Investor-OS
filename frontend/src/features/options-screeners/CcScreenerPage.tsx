import type { PortfolioResponse } from '@/api/portfolio'
import { SingleLegScreenerRoute } from '@/features/options-screeners/SingleLegScreenerRoute'
import type { CoveredCallCandidate } from '@/features/options-screeners/lib/screenerResults'

export function CcScreenerPage({
  portfolio,
  selectedAccount,
  onCandidateActivate,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  onCandidateActivate?: (candidate: CoveredCallCandidate) => void
}) {
  return (
    <SingleLegScreenerRoute
      kind="cc"
      portfolio={portfolio}
      selectedAccount={selectedAccount}
      onCandidateActivate={onCandidateActivate}
    />
  )
}
