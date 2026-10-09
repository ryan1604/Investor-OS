import type {
  CashSecuredPutCandidate,
  CoveredCallCandidate,
  CreditSpreadCandidate,
  ScreenerCandidate,
} from '@/api/optionsScreeners'
import { formatNumber } from '@/lib/format'

export function formatScreenerPrice(value: number) {
  return fixedTwoDecimals(value)
}

export function formatScreenerPercentage(value: number) {
  return `${fixedTwoDecimals(value)}%`
}

function fixedTwoDecimals(value: number) {
  return formatNumber(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function cspCandidates(
  candidates: ScreenerCandidate[],
) {
  return candidates.filter(
    (candidate): candidate is CashSecuredPutCandidate =>
      candidate.strategy === 'csp',
  )
}

export function ccCandidates(
  candidates: ScreenerCandidate[],
) {
  return candidates.filter(
    (candidate): candidate is CoveredCallCandidate =>
      candidate.strategy === 'cc',
  )
}

export function csCandidates(
  candidates: ScreenerCandidate[],
) {
  return candidates.filter(
    (candidate): candidate is CreditSpreadCandidate =>
      candidate.strategy === 'put_credit_spread' ||
      candidate.strategy === 'call_credit_spread',
  )
}
