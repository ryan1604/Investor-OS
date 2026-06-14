import type { ChartConfig } from '@/components/ui/chart'

const TRACKER_CHART_PALETTE = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'oklch(0.65 0.17 35)',
  'oklch(0.6 0.17 285)',
  'oklch(0.68 0.16 95)',
] as const

export function strategyChartKey(index: number) {
  return `strategy_${index}`
}

export function strategyChartColor(index: number) {
  return TRACKER_CHART_PALETTE[index % TRACKER_CHART_PALETTE.length]
}

export function strategyChartConfig(strategies: string[]) {
  return Object.fromEntries(
    strategies.map((strategy, index) => [
      strategyChartKey(index),
      {
        label: strategy,
        color: strategyChartColor(index),
      },
    ]),
  ) satisfies ChartConfig
}
