import type {
  AnalysisCoverage,
  AnalysisUnsupportedPosition,
} from '@/api/portfolioAnalysis'
import { Alert } from '@/components/ui/alert'
import { formatNumber } from '@/lib/format'

type CoverageBannerProps = {
  coverage: AnalysisCoverage
  unsupported: AnalysisUnsupportedPosition[]
}

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function coverageNotes(coverage: AnalysisCoverage) {
  return [
    coverage.fallback_greeks
      ? `${plural(coverage.fallback_greeks, 'position')} used fallback Greeks`
      : null,
    coverage.fallback_beta
      ? `${plural(coverage.fallback_beta, 'position')} used a fallback beta of 1.0`
      : null,
    coverage.missing_price
      ? `${plural(coverage.missing_price, 'position')} had no price and count as 0`
      : null,
    coverage.fx_converted
      ? `${plural(coverage.fx_converted, 'position')} converted to USD at IB's rate`
      : null,
    coverage.unsupported
      ? `${plural(coverage.unsupported, 'position')} excluded as unsupported`
      : null,
  ].filter((note): note is string => note !== null)
}

export function CoverageBanner({ coverage, unsupported }: CoverageBannerProps) {
  const notes = coverageNotes(coverage)
  if (!notes.length) {
    return null
  }

  return (
    <Alert variant="muted" className="mt-6">
      <p className="font-medium text-foreground">
        Coverage: {notes.join('; ')} (of {plural(coverage.positions, 'position')}).
      </p>
      {unsupported.length ? (
        <ul className="mt-1 list-disc pl-5">
          {unsupported.map((position) => (
            <li key={`${position.con_id}-${position.symbol}`}>
              {position.local_symbol ?? position.symbol} ({position.sec_type},{' '}
              {formatNumber(position.quantity)}): {position.reason}
            </li>
          ))}
        </ul>
      ) : null}
    </Alert>
  )
}
