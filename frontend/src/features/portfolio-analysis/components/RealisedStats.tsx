import type { AnalysisRealisedStats, AnalysisRealisedValue } from '@/api/portfolioAnalysis'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Metric } from '@/features/portfolio-analysis/components/AnalysisSummaryCards'
import { InfoHint } from '@/features/portfolio-analysis/components/InfoHint'
import { historyDate } from '@/features/portfolio-analysis/lib/history'
import { formatNumber, formatOptionalPercent } from '@/lib/format'

const CASH_FLOW_NOTE =
  'From the daily NAV history. Deposits and withdrawals count as gains and losses, ' +
  'so they distort these figures.'

function percentValue(stat: AnalysisRealisedValue) {
  return formatOptionalPercent(stat.value)
}

function betaValue(stat: AnalysisRealisedValue) {
  return stat.value === null
    ? '-'
    : formatNumber(stat.value, { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

function observationDetail(stat: AnalysisRealisedValue, unit: string) {
  return stat.value === null ? undefined : `${stat.observations} ${unit}`
}

function windowText(realised: AnalysisRealisedStats) {
  if (!realised.start_date || !realised.end_date) {
    return 'No daily NAV history yet.'
  }
  const year = (value: string) => value.slice(0, 4)
  return (
    `${historyDate(realised.start_date)} ${year(realised.start_date)} - ` +
    `${historyDate(realised.end_date)} ${year(realised.end_date)} · ` +
    `${realised.nav_observations} daily NAVs (${realised.currency})`
  )
}

export function RealisedStats({ realised }: { realised: AnalysisRealisedStats }) {
  const {
    volatility_20d_percent: vol20,
    volatility_60d_percent: vol60,
    max_drawdown_percent: maxDrawdown,
    current_drawdown_percent: currentDrawdown,
    beta,
  } = realised

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-1 text-base">
          Realised Risk
          <InfoHint note={CASH_FLOW_NOTE} />
        </CardTitle>
        <p className="text-xs text-muted-foreground">{windowText(realised)}</p>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <Metric
            label="Volatility 20D"
            value={percentValue(vol20)}
            detail={vol20.value === null ? undefined : 'annualised'}
            note={vol20.reason ?? undefined}
          />
          <Metric
            label="Volatility 60D"
            value={percentValue(vol60)}
            detail={vol60.value === null ? undefined : 'annualised'}
            note={vol60.reason ?? undefined}
          />
          <Metric
            label="Max Drawdown"
            value={percentValue(maxDrawdown)}
            note={maxDrawdown.reason ?? undefined}
          />
          <Metric
            label="Current Drawdown"
            value={percentValue(currentDrawdown)}
            note={currentDrawdown.reason ?? undefined}
          />
          <Metric
            label="Realised Beta"
            value={betaValue(beta)}
            detail={observationDetail(beta, 'days vs SPY')}
            note={beta.reason ?? undefined}
          />
        </div>
      </CardContent>
    </Card>
  )
}
