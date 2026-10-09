import type {
  OptionsScreenerFilters,
  OptionsScreenerQuoteRefreshResponse,
} from '@/api/optionsScreeners'
import { daysToExpiration } from '@/lib/dates'

export function singleLegRefreshedContractWarning({
  refreshed,
  filters,
  annualizedReturnDenominator,
  message,
}: {
  refreshed: OptionsScreenerQuoteRefreshResponse
  filters: OptionsScreenerFilters
  annualizedReturnDenominator: number
  message: string
}) {
  return refreshedContractMatchesFilters(
    refreshed,
    filters,
    annualizedReturnDenominator,
  )
    ? null
    : message
}

function refreshedContractMatchesFilters(
  refreshed: OptionsScreenerQuoteRefreshResponse,
  filters: OptionsScreenerFilters,
  annualizedReturnDenominator: number,
) {
  const absoluteDelta = refreshed.delta === null ? null : Math.abs(refreshed.delta)
  const refreshedDte = daysToExpiration(refreshed.expiration)
  const annualizedReturn =
    refreshedDte > 0 &&
    refreshed.midpoint > 0 &&
    annualizedReturnDenominator > 0
      ? (refreshed.midpoint / annualizedReturnDenominator) *
        (365 / refreshedDte) *
        100
      : null

  return refreshedValuesMatchFilters(refreshedDte, absoluteDelta, annualizedReturn, filters)
}

export function refreshedValuesMatchFilters(
  dte: number,
  absoluteDelta: number | null,
  annualizedReturn: number | null,
  filters: OptionsScreenerFilters,
) {
  return (
    dte >= filters.minimum_dte &&
    dte <= filters.maximum_dte &&
    absoluteDelta !== null &&
    absoluteDelta >= filters.minimum_absolute_delta &&
    absoluteDelta <= filters.maximum_absolute_delta &&
    annualizedReturn !== null &&
    annualizedReturn >= filters.minimum_annualized_return
  )
}
