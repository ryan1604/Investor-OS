import { useState } from 'react'
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartContainer, ChartTooltip } from '@/components/ui/chart'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useNavHistory } from '@/features/portfolio/hooks/useNavHistory'
import { availableNavRanges, currencySegments, navPoints, navDate, navRangeRows, type NavRange } from '@/features/portfolio/lib/navChart'
import { formatCompactCurrency, formatOptionalCurrency } from '@/lib/format'

const syncLabels = { unconfigured: 'Automatic updates not configured', pending: 'Waiting for the first report', syncing: 'Updating from IBKR…', current: 'Up to date', stale: 'Waiting for a newer closing report', failed: 'Update failed · saved history shown' }

export function DailyNavChart({ account }: { account: string | undefined }) {
  const { data, error, isLoading } = useNavHistory(account)
  const [range, setRange] = useState<NavRange>('1Y')
  const rows = data?.rows ?? []
  const [percentage, setPercentage] = useState(false)
  const ranges = availableNavRanges(rows)
  const activeRange = ranges.includes(range) ? range : 'All'
  const segments = currencySegments(navRangeRows(rows, activeRange))
  return <Card className="mt-6" data-testid="daily-nav-chart">
    <CardHeader className="gap-4 sm:flex sm:flex-row sm:items-start sm:justify-between">
      <div>
        <CardTitle className="text-base">Net account value</CardTitle>
        <div className="mt-1 text-xs text-muted-foreground" role="status">
          {account && <span>{account} · </span>}
          {isLoading ? 'Loading daily history…' : data ? syncLabels[data.sync.state] : ''}
          {data?.sync.last_successful_sync && <span> · Last synced {new Date(data.sync.last_successful_sync).toLocaleString()}</span>}
        </div>
      </div>
      <div className="flex flex-wrap gap-3 sm:justify-end">
        <ToggleGroup type="single" value={percentage ? 'percentage' : 'amount'} onValueChange={value => { if (value) setPercentage(value === 'percentage') }} variant="outline" size="sm" aria-label="NAV display">
          <ToggleGroupItem value="amount">Amount</ToggleGroupItem>
          <ToggleGroupItem value="percentage">Percentage</ToggleGroupItem>
        </ToggleGroup>
        <ToggleGroup type="single" value={activeRange} onValueChange={value => { if (ranges.includes(value as NavRange)) setRange(value as NavRange) }} variant="outline" size="sm" aria-label="NAV date range" className="flex-wrap">
          {ranges.map(value => <ToggleGroupItem key={value} value={value}>{value}</ToggleGroupItem>)}
        </ToggleGroup>
      </div>
    </CardHeader>
    <CardContent>
      {(error || data?.sync.error) && <p role="alert" className="mb-4 text-sm text-destructive">{error || data?.sync.error}</p>}
      {data?.currency_changed && <p className="mb-3 text-xs text-muted-foreground">Base currency changed. Each currency period is shown separately.</p>}
      {!isLoading && !segments.length && <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">{!account ? 'Select an account to view history.' : rows.length ? 'No closing values in this range.' : 'No daily NAV history yet.'}</div>}
      {segments.map(segment => {
        const currency = segment[0].currency
        const points = navPoints(segment, percentage)
        const formatValue = (value: number) => percentage ? `${value.toFixed(2)}%` : `${formatOptionalCurrency(value, currency)} ${currency}`
        return <section key={segment[0].report_date} aria-label={`Daily NAV in ${currency}`}>
          {data?.currency_changed && <p className="mt-3 text-sm">{currency} · {navDate(segment[0].report_date)} – {navDate(segment.at(-1)!.report_date)}</p>}
          {!points.length ? <p className="py-16 text-center text-sm text-muted-foreground">Percentage change requires a positive starting NAV.</p> : <ChartContainer config={{ value: { label: 'Net account value', color: 'var(--chart-portfolio-value)' } }} className="h-80 w-full" initialDimension={{ width: 900, height: 320 }}>
            <LineChart data={points} accessibilityLayer margin={{ top: 16, left: 8, right: 20, bottom: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="date" type="number" domain={['dataMin', 'dataMax']} tickFormatter={navDate} minTickGap={48} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={value => percentage ? `${value.toFixed(1)}%` : formatCompactCurrency(value, currency)} width={80} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
              <ChartTooltip content={({ active, payload }) => active && payload?.length ? <div className="rounded-lg border bg-background p-3 text-xs shadow-lg"><p>{navDate(payload[0].payload.date)}</p><p className="mt-1 font-medium tabular-nums">{formatValue(payload[0].payload.value)}</p></div> : null} />
              <Line dataKey="value" type="linear" stroke="var(--color-value)" strokeWidth={2} dot={points.length === 1 ? { r: 4 } : false} activeDot={{ r: 4 }} isAnimationActive={false} />
            </LineChart>
          </ChartContainer>}
        </section>
      })}
    </CardContent>
  </Card>
}
