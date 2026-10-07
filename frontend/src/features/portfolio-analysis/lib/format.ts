import type {
  AnalysisBetaSource,
  AnalysisGreeksSource,
  AnalysisLeg,
  AnalysisMarginEstimate,
} from '@/api/portfolioAnalysis'
import { formatNumber } from '@/lib/format'

export function formatMultiple(value: number | null) {
  if (value === null) {
    return '-'
  }

  return `${formatNumber(value, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}x`
}

export function formatWholeCurrency(value: number | null) {
  if (value === null) {
    return '-'
  }

  return formatNumber(value, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  })
}

export function betaFallbackNote(source: AnalysisBetaSource, observations: number | null) {
  if (source !== 'fallback') {
    return null
  }
  return observations
    ? `Beta 1.0 fallback: only ${observations} daily returns against SPY (60 needed).`
    : 'Beta 1.0 fallback: no daily history against SPY yet.'
}

const GREEKS_NOTES: Record<AnalysisGreeksSource, string | null> = {
  ib: null,
  fallback: "Missing IB Greeks filled from Black-Scholes at IB's IV.",
  solved_iv: 'Greeks from Black-Scholes at an IV solved from the option price.',
  missing: 'No Greeks: the underlying price or IV is unavailable, so this leg counts as 0.',
}

export function legNotes(leg: AnalysisLeg) {
  const notes: string[] = []
  const greeksNote = leg.greeks_source ? GREEKS_NOTES[leg.greeks_source] : null
  if (greeksNote) {
    notes.push(greeksNote)
  }
  if (leg.flags.includes('mark_price')) {
    notes.push("No quote from IB, so the IV was solved from IB's position mark.")
  }
  if (leg.flags.includes('missing_price')) {
    notes.push('No price available, so this leg counts as 0.')
  }
  if (leg.flags.includes('fx_converted')) {
    notes.push(`Converted from ${leg.currency} at IB's rate ${leg.fx_rate}.`)
  }
  return notes
}

export function legLabel(leg: AnalysisLeg) {
  if (leg.sec_type === 'STK') {
    return `${formatNumber(leg.quantity)} shares`
  }
  const expiry = leg.expiry
    ? `${leg.expiry.slice(0, 4)}-${leg.expiry.slice(4, 6)}-${leg.expiry.slice(6, 8)}`
    : ''
  const strike = leg.strike === null ? '' : formatNumber(leg.strike)
  return `${formatNumber(leg.quantity)} x ${expiry} ${strike}${leg.right ?? ''}`
}

// A signed shock such as -30% or +25%.
export function formatShock(value: number) {
  return `${value > 0 ? '+' : ''}${formatNumber(value, { maximumFractionDigits: 1 })}%`
}

export function marginCallDistanceText(margin: AnalysisMarginEstimate) {
  if (margin.margin_call_beyond_path) {
    return '> 30%'
  }
  if (margin.distance_to_margin_call_percent === null) {
    return '-'
  }
  return `${formatNumber(margin.distance_to_margin_call_percent, {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  })}%`
}
