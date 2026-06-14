import { useMemo } from 'react'
import { Cell, Pie, PieChart } from 'recharts'

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { StatsChartEmptyState } from '@/features/options-trade-tracker/components/MonthlyPerformanceChart'
import {
  deriveStrategyCountPieData,
  type CompletedTradeProjection,
  type StrategyCountPieSlice,
} from '@/features/options-trade-tracker/lib/tradeTracker'
import {
  strategyChartColor,
  strategyChartConfig,
  strategyChartKey,
} from '@/features/options-trade-tracker/lib/trackerCharts'
import { formatNumber } from '@/lib/format'

type StrategyExecutionPieChartProps = {
  completedTrades: CompletedTradeProjection[]
}

export function StrategyExecutionPieChart({
  completedTrades,
}: StrategyExecutionPieChartProps) {
  const data = useMemo(
    () => deriveStrategyCountPieData(completedTrades),
    [completedTrades],
  )
  const keyedData = useMemo(() => toKeyedPieData(data), [data])
  const config = useMemo(
    () => strategyChartConfig(data.map((slice) => slice.strategy)),
    [data],
  )

  return (
    <section className="rounded-lg border border-border bg-background p-3">
      <div>
        <h3 className="font-medium text-foreground">Strategy execution</h3>
      </div>

      {data.length > 0 ? (
        <ChartContainer
          config={config}
          className="mt-3 h-80 w-full"
          initialDimension={{ width: 520, height: 320 }}
        >
          <PieChart accessibilityLayer>
            <ChartTooltip
              content={
                <ChartTooltipContent
                  nameKey="strategyKey"
                  formatter={(value) => formatNumber(Number(value))}
                />
              }
            />
            <Pie
              data={keyedData}
              dataKey="count"
              nameKey="strategyKey"
              innerRadius={62}
              outerRadius={104}
              paddingAngle={2}
            >
              {keyedData.map((slice, index) => (
                <Cell
                  key={slice.strategyKey}
                  fill={strategyChartColor(index)}
                />
              ))}
            </Pie>
            <ChartLegend
              content={<ChartLegendContent nameKey="strategyKey" />}
            />
          </PieChart>
        </ChartContainer>
      ) : (
        <StatsChartEmptyState message="Complete valid trades to chart strategy execution." />
      )}
    </section>
  )
}

function toKeyedPieData(slices: StrategyCountPieSlice[]) {
  return slices.map((slice, index) => ({
    ...slice,
    strategyKey: strategyChartKey(index),
  }))
}
