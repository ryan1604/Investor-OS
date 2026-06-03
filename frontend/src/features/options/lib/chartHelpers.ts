import {
  ColorType,
  createChart,
  type IChartApi,
  type LineData,
  type Time,
} from 'lightweight-charts'

import { chartColors } from '@/features/options/lib/chartColors'

type SetupChartOptions = {
  height: number
  timeVisible?: boolean
}

export function setupOptionsChart(
  container: HTMLDivElement,
  { height, timeVisible }: SetupChartOptions,
): { chart: IChartApi; cleanup: () => void } {
  const colors = chartColors()
  const chart = createChart(container, {
    autoSize: true,
    height,
    layout: {
      background: {
        type: ColorType.Solid,
        color: colors.background,
      },
      textColor: colors.mutedForeground,
      fontFamily: 'Geist Variable, sans-serif',
    },
    grid: {
      vertLines: { color: colors.border },
      horzLines: { color: colors.border },
    },
    rightPriceScale: {
      borderColor: colors.border,
    },
    timeScale: {
      borderColor: colors.border,
      timeVisible,
    },
    crosshair: {
      vertLine: { color: colors.foreground },
      horzLine: { color: colors.foreground },
    },
  })

  const observer = new ResizeObserver(() => {
    chart.timeScale().fitContent()
  })
  observer.observe(container)

  return {
    chart,
    cleanup: () => {
      observer.disconnect()
      chart.remove()
    },
  }
}

export function nullableLineData(
  points: { time: string; value: number | null }[],
): LineData<Time>[] {
  return points
    .filter((point): point is { time: string; value: number } => {
      return point.value !== null
    })
    .map((point) => ({
      time: point.time,
      value: point.value,
    }))
}

export function referenceLineData(times: string[], value: number): LineData<Time>[] {
  return times.map((time) => ({
    time,
    value,
  }))
}
