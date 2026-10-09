import type { PortfolioResponse } from '@/api/portfolio'
import { SingleLegScreenerRoute } from '@/features/options-screeners/SingleLegScreenerRoute'

export function CspScreenerPage({
  portfolio,
  selectedAccount,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}) {
  return (
    <SingleLegScreenerRoute
      screener="csp"
      portfolio={portfolio}
      selectedAccount={selectedAccount}
    />
  )
}
