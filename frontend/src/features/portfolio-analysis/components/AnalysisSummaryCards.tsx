import type { AnalysisSummary } from '@/api/portfolioAnalysis'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { InfoHint } from '@/features/portfolio-analysis/components/InfoHint'
import {
  formatMultiple,
  formatWholeCurrency,
} from '@/features/portfolio-analysis/lib/format'
import { limitTextClass, type LimitBands } from '@/features/portfolio-analysis/lib/limits'
import { formatOptionalPercent, signedTextClassName } from '@/lib/format'

const METRIC_COUNT = 7

type MetricProps = {
  label: string
  value: string
  detail?: string
  // Shown as an info tooltip next to the label.
  note?: string
  valueClassName?: string
}

export function Metric({
  label,
  value,
  detail,
  note,
  valueClassName = 'text-foreground',
}: MetricProps) {
  return (
    <div className="min-w-0 border-t pt-3 first:border-t-0 first:pt-0 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0 sm:first:border-l-0 sm:first:pl-0">
      <div className="flex items-center gap-1 text-xs font-medium uppercase tracking-normal text-muted-foreground">
        {label}
        {note ? <InfoHint note={note} /> : null}
      </div>
      <div className={`mt-1 flex min-h-8 min-w-0 flex-wrap items-baseline gap-x-2 ${valueClassName}`}>
        <span className="truncate text-xl font-semibold tabular-nums leading-tight">{value}</span>
        {detail && detail !== '-' ? (
          <span className="text-sm font-medium tabular-nums text-muted-foreground">{detail}</span>
        ) : null}
      </div>
    </div>
  )
}

type AnalysisSummaryCardsProps = {
  isLoading: boolean
  summary: AnalysisSummary | null
  // Band colours for metrics with a saved risk limit.
  bands?: LimitBands
}

export function AnalysisSummaryCards({
  isLoading,
  summary,
  bands = {},
}: AnalysisSummaryCardsProps) {
  if (!isLoading && !summary) {
    return null
  }

  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-7">
          {summary ? (
            <>
              <Metric
                label="Net Liquidation"
                value={formatWholeCurrency(summary.net_liquidation)}
              />
              <Metric
                label="Beta-Wtd Delta"
                value={formatMultiple(summary.beta_weighted_delta_multiple)}
                detail={formatWholeCurrency(summary.beta_weighted_delta)}
                valueClassName={limitTextClass(bands, 'beta_weighted_delta_multiple')}
              />
              <Metric
                label="Theta / Day"
                value={formatWholeCurrency(summary.net_theta)}
                valueClassName={signedTextClassName(summary.net_theta)}
              />
              <Metric label="Net Vega" value={formatWholeCurrency(summary.net_vega)} />
              <Metric
                label="Margin Used"
                value={formatOptionalPercent(summary.margin_utilisation_percent)}
                detail={formatWholeCurrency(summary.maintenance_margin)}
                valueClassName={limitTextClass(bands, 'margin_utilisation_percent')}
              />
              <Metric
                label="Assignment"
                value={formatOptionalPercent(summary.assignment_exposure_percent)}
                detail={formatWholeCurrency(summary.assignment_exposure)}
                valueClassName={limitTextClass(bands, 'assignment_exposure_percent')}
              />
              <Metric
                label="Largest Underlying"
                value={formatOptionalPercent(summary.largest_underlying_percent)}
                detail={summary.largest_underlying ?? undefined}
                valueClassName={limitTextClass(bands, 'largest_underlying_percent')}
              />
            </>
          ) : (
            Array.from({ length: METRIC_COUNT }).map((_, index) => (
              <div key={index}>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-2 h-8 w-28" />
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  )
}
