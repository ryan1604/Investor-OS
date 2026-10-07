import {
  formatLimitValue,
  LIMIT_BAND_TEXT_CLASS,
  limitRule,
  type LimitBand,
  type LimitStatus,
} from '@/features/portfolio-analysis/lib/limits'
import { cn } from '@/lib/utils'

const BAND_DOT_CLASS: Record<LimitBand, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-500',
  red: 'bg-red-500',
}

const BAND_LABEL: Record<LimitBand, string> = {
  green: 'within limit',
  amber: 'near limit',
  red: 'over limit',
}

type LimitStatusStripProps = {
  statuses: LimitStatus[]
}

// One chip per saved limit; hidden until the account has saved limits.
export function LimitStatusStrip({ statuses }: LimitStatusStripProps) {
  if (!statuses.length) {
    return null
  }

  return (
    <ul className="mt-4 flex flex-wrap gap-2 text-xs" aria-label="Risk limit status">
      {statuses.map(({ definition, limit, value, band }) => (
        <li
          key={definition.key}
          className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1"
          data-band={band ?? 'none'}
          title={`${definition.label}: ${formatLimitValue(definition, value)} (limit ${limitRule(definition, limit)})${band ? `, ${BAND_LABEL[band]}` : ', no data'}`}
        >
          <span
            className={cn('size-2 rounded-full', band ? BAND_DOT_CLASS[band] : 'bg-muted-foreground/40')}
          />
          <span className="text-muted-foreground">{definition.label}</span>
          <span className={cn('font-medium tabular-nums', band && LIMIT_BAND_TEXT_CLASS[band])}>
            {formatLimitValue(definition, value)}
          </span>
          <span className="text-muted-foreground">{limitRule(definition, limit)}</span>
        </li>
      ))}
    </ul>
  )
}
