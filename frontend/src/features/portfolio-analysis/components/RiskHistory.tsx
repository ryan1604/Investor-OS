import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from 'recharts'

import type { AnalysisRiskSnapshot, RiskLimit } from '@/api/portfolioAnalysis'
import { Alert } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartContainer, ChartTooltip } from '@/components/ui/chart'
import {
  HISTORY_METRICS,
  historyDate,
  historyLimitLines,
  historyPoints,
  SNAPSHOT_KIND_LABEL,
  type HistoryMetric,
  type HistoryPoint,
} from '@/features/portfolio-analysis/lib/history'

type DotProps = {
  cx?: number
  cy?: number
  index?: number
  payload?: HistoryPoint
  value?: number | null
}

// Intraday snapshots are hollow; after-close snapshots are filled.
function SnapshotDot({ cx, cy, index, payload, value }: DotProps) {
  if (cx === undefined || cy === undefined || value === null || value === undefined || !payload?.kind) {
    return <g key={index} />
  }
  const intraday = payload.kind === 'intraday'
  return (
    <circle
      key={index}
      cx={cx}
      cy={cy}
      r={intraday ? 4 : 3}
      data-kind={payload.kind}
      fill={intraday ? 'var(--background)' : 'var(--color-value)'}
      stroke="var(--color-value)"
      strokeWidth={intraday ? 2 : 1}
    />
  )
}

type HistoryChartProps = {
  metric: HistoryMetric
  points: HistoryPoint[]
  limits: RiskLimit[]
}

function HistoryChart({ metric, points, limits }: HistoryChartProps) {
  const limitLines = historyLimitLines(metric, limits, points)

  return (
    <section aria-label={`${metric.label} history`}>
      <h3 className="text-xs font-medium uppercase text-muted-foreground">{metric.label}</h3>
      <ChartContainer
        config={{ value: { label: metric.label, color: 'var(--chart-1)' } }}
        className="mt-2 h-48 w-full"
        initialDimension={{ width: 480, height: 192 }}
      >
        <LineChart data={points} accessibilityLayer margin={{ top: 8, left: 4, right: 12, bottom: 4 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="date"
            type="number"
            domain={['dataMin', 'dataMax']}
            tickFormatter={historyDate}
            minTickGap={32}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tickFormatter={(value: number) => metric.format(value)}
            width={72}
            tickLine={false}
            axisLine={false}
            domain={['auto', 'auto']}
          />
          {limitLines.map((limit) => (
            <ReferenceLine
              key={limit}
              y={limit}
              ifOverflow="extendDomain"
              stroke="var(--color-red-500)"
              strokeDasharray="4 4"
              label={{
                value: `Limit ${metric.format(limit)}`,
                position: 'insideTopRight',
                fontSize: 10,
                fill: 'var(--color-red-500)',
              }}
            />
          ))}
          <ChartTooltip
            content={({ active, payload }) => {
              const point = payload?.[0]?.payload as HistoryPoint | undefined
              if (!active || !point?.kind) {
                return null
              }
              return (
                <div className="rounded-lg border bg-background p-3 text-xs shadow-lg">
                  <p>
                    {historyDate(point.date)} · {SNAPSHOT_KIND_LABEL[point.kind]}
                  </p>
                  <p className="mt-1 font-medium tabular-nums">{metric.format(point[metric.key])}</p>
                </div>
              )
            }}
          />
          <Line
            dataKey={metric.key}
            type="linear"
            stroke="var(--color-value)"
            strokeWidth={2}
            connectNulls={false}
            dot={SnapshotDot}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ChartContainer>
    </section>
  )
}

type RiskHistoryProps = {
  snapshots: AnalysisRiskSnapshot[]
  limits: RiskLimit[]
  isLoaded: boolean
  error: string | null
}

export function RiskHistory({ snapshots, limits, isLoaded, error }: RiskHistoryProps) {
  const points = historyPoints(snapshots)

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="text-base">Risk History</CardTitle>
        <p className="text-xs text-muted-foreground">
          One snapshot per session, recorded while this page is open. Hollow points are intraday;
          gaps are sessions without a snapshot. Dashed lines are saved limits.
        </p>
      </CardHeader>
      <CardContent>
        {error ? (
          <Alert variant="destructive" className="mb-4">
            {error}
          </Alert>
        ) : null}
        {!points.length ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {isLoaded ? 'No risk history yet.' : 'Loading risk history...'}
          </p>
        ) : (
          <div className="grid gap-6 lg:grid-cols-2">
            {HISTORY_METRICS.map((metric) => (
              <HistoryChart key={metric.key} metric={metric} points={points} limits={limits} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
