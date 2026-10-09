import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ReferenceLine, XAxis, YAxis } from 'recharts'

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import {
  ToggleGroup,
  ToggleGroupItem,
} from '@/components/ui/toggle-group'
import {
  deriveNetMonthlyChartData,
  deriveStackedMonthlyChartData,
  deriveStrategyStats,
  type CompletedTradeProjection,
  type StackedMonthlyChartRow,
} from '@/features/options-trade-tracker/lib/tradeTracker'
import {
  strategyChartColor,
  strategyChartConfig,
  strategyChartKey,
} from '@/features/options-trade-tracker/lib/trackerCharts'
import { formatCompactCurrency, formatCurrency } from '@/lib/format'

type MonthlyChartMode = 'strategy' | 'net'

type MonthlyPerformanceChartProps = {
  completedTrades: CompletedTradeProjection[]
  strategyOptions: string[]
}

export function MonthlyPerformanceChart({
  completedTrades,
  strategyOptions,
}: MonthlyPerformanceChartProps) {
  const [mode, setMode] = useState<MonthlyChartMode>('strategy')
  const activeStrategies = useMemo(
    () =>
      deriveStrategyStats(completedTrades, strategyOptions).rows
        .filter((row) => row.count > 0)
        .map((row) => row.strategy),
    [completedTrades, strategyOptions],
  )
  const stackedData = useMemo(
    () => toKeyedStackedRows(completedTrades, activeStrategies),
    [completedTrades, activeStrategies],
  )
  const netData = useMemo(
    () => deriveNetMonthlyChartData(completedTrades),
    [completedTrades],
  )
  const strategyConfig = useMemo(
    () => strategyChartConfig(activeStrategies),
    [activeStrategies],
  )
  const netConfig = {
    total: {
      label: 'Net P&L',
      color: 'var(--chart-1)',
    },
  }
  const hasCompletedData = activeStrategies.length > 0

  return (
    <section className="rounded-lg border border-border bg-background p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="font-medium text-foreground">Monthly performance</h3>
        </div>
        <ToggleGroup
          type="single"
          value={mode}
          onValueChange={(value) => {
            if (value === 'strategy' || value === 'net') {
              setMode(value)
            }
          }}
          variant="outline"
          size="sm"
          aria-label="Monthly performance mode"
        >
          <ToggleGroupItem value="strategy">By strategy</ToggleGroupItem>
          <ToggleGroupItem value="net">Net</ToggleGroupItem>
        </ToggleGroup>
      </div>

      {hasCompletedData ? (
        mode === 'strategy' ? (
          <ChartContainer
            config={strategyConfig}
            className="mt-3 h-80 w-full"
            initialDimension={{ width: 960, height: 320 }}
          >
            <BarChart
              accessibilityLayer
              data={stackedData}
              stackOffset="sign"
              margin={{ top: 8, left: 8, right: 8 }}
            >
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
              />
              <YAxis
                tickFormatter={(value) => formatCompactCurrency(Number(value), 'USD', 'usd-thousands')}
                tickLine={false}
                axisLine={false}
                width={72}
              />
              <ChartTooltip
                cursor={false}
                content={
                  <ChartTooltipContent
                    nameKey="dataKey"
                    valueFormatter={(value) => formatCurrency(Number(value))}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              {/* Keep a numeric domain even when every strategy nets to zero. */}
              <ReferenceLine
                y={0}
                ifOverflow="extendDomain"
                stroke="var(--muted-foreground)"
              />
              {activeStrategies.map((strategy, index) => (
                <Bar
                  key={strategy}
                  dataKey={strategyChartKey(index)}
                  name={strategy}
                  stackId="strategy"
                  fill={strategyChartColor(index)}
                />
              ))}
            </BarChart>
          </ChartContainer>
        ) : (
          <ChartContainer
            config={netConfig}
            className="mt-3 h-80 w-full"
            initialDimension={{ width: 960, height: 320 }}
          >
            <BarChart
              accessibilityLayer
              data={netData}
              margin={{ top: 8, left: 8, right: 8 }}
            >
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
              />
              <YAxis
                tickFormatter={(value) => formatCompactCurrency(Number(value), 'USD', 'usd-thousands')}
                tickLine={false}
                axisLine={false}
                width={72}
              />
              <ChartTooltip
                cursor={false}
                content={
                  <ChartTooltipContent
                    nameKey="dataKey"
                    valueFormatter={(value) => formatCurrency(Number(value))}
                  />
                }
              />
              <ReferenceLine
                y={0}
                ifOverflow="extendDomain"
                stroke="var(--muted-foreground)"
              />
              <Bar
                dataKey="total"
                name="Net P&L"
                fill="var(--chart-1)"
              />
            </BarChart>
          </ChartContainer>
        )
      ) : (
        <StatsChartEmptyState message="Complete valid trades to chart monthly performance." />
      )}
    </section>
  )
}

export function StatsChartEmptyState({ message }: { message: string }) {
  return (
    <div className="mt-3 flex min-h-60 items-center justify-center rounded-lg border border-dashed bg-muted/20 px-4 text-center text-sm text-muted-foreground">
      {message}
    </div>
  )
}

function toKeyedStackedRows(
  completedTrades: CompletedTradeProjection[],
  strategies: string[],
) {
  const strategyIndexes = new Map(
    strategies.map((strategy, index) => [strategy, strategyChartKey(index)]),
  )

  return deriveStackedMonthlyChartData(completedTrades, strategies).map((row) => {
    const keyedRow: StackedMonthlyChartRow = {
      month: row.month,
      label: row.label,
    }

    strategies.forEach((strategy) => {
      const key = strategyIndexes.get(strategy)
      if (key !== undefined) {
        keyedRow[key] = Number(row[strategy] ?? 0)
      }
    })

    return keyedRow
  })
}
