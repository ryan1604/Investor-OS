import type { PortfolioResponse } from '@/api/portfolio'
import { SingleLegScreenerRoute } from '@/features/options-screeners/SingleLegScreenerRoute'

export function CcScreenerPage({
  portfolio,
  selectedAccount,
}: {
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}) {
  return (
    <SingleLegScreenerRoute
      screener="cc"
      portfolio={portfolio}
      selectedAccount={selectedAccount}
    />
  )
}
