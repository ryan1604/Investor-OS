import type {
  CreditSpreadCandidate,
  OptionsScreenerFilters,
  OptionsScreenerSpreadQuoteRefreshResponse,
} from '@/api/optionsScreeners'
import { refreshedValuesMatchFilters } from '@/features/options-screeners/lib/singleLegWarnings'
import { daysToExpiration } from '@/lib/dates'

export function refreshedCandidateWarning(
  refreshed: OptionsScreenerSpreadQuoteRefreshResponse,
  candidate: CreditSpreadCandidate,
  filters: OptionsScreenerFilters,
) {
  const refreshedDte = daysToExpiration(refreshed.expiration)
  const absoluteDelta =
    refreshed.short_delta === null ? null : Math.abs(refreshed.short_delta)
  const width = Math.abs(refreshed.short_strike - refreshed.long_strike)
  const expectedWidth = Math.abs(candidate.short_strike - candidate.long_strike)
  const annualizedReturn =
    refreshedDte > 0 && refreshed.maximum_loss > 0
      ? (refreshed.net_midpoint / refreshed.maximum_loss) *
        (365 / refreshedDte) *
        100
      : null
  const matches =
    refreshedValuesMatchFilters(refreshedDte, absoluteDelta, annualizedReturn, filters) &&
    Math.abs(width - expectedWidth) <= 1e-6 &&
    refreshed.net_midpoint > 0 &&
    refreshed.net_midpoint < width &&
    refreshed.maximum_loss > 0

  return matches
    ? null
    : 'The refreshed spread no longer satisfies the current CS scan filters, exact width, or maximum-loss rules.'
}
