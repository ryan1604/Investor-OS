import { useEffect, useMemo, useRef } from 'react'

import {
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'

import type {
  OptionsAnalysisResponse,
  OptionsChartLiveMessage,
} from '@/api/options'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  nullableLineData,
  referenceLineData,
  setupOptionsChart,
} from '@/features/options/lib/chartHelpers'

type RsiChartProps = {
  analysis: OptionsAnalysisResponse
  latestUpdate: OptionsChartLiveMessage | null
  onChartReady?: (chart: IChartApi | null) => void
}

export function RsiChart({
  analysis,
  latestUpdate,
  onChartReady,
}: RsiChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const rsiRef = useRef<ISeriesApi<'Line'> | null>(null)
  const overboughtRef = useRef<ISeriesApi<'Line'> | null>(null)
  const oversoldRef = useRef<ISeriesApi<'Line'> | null>(null)

  const currentRsi = useMemo(() => {
    if (
      latestUpdate?.ticker === analysis.ticker &&
      latestUpdate.rsi.value !== null
    ) {
      return latestUpdate.rsi.value
    }

    return [...analysis.rsi]
      .reverse()
      .find((point) => point.value !== null)?.value ?? null
  }, [analysis.rsi, analysis.ticker, latestUpdate])

  const rsiData = useMemo(() => {
    return nullableLineData(
      analysis.rsi.map((point) => ({
        time: point.date,
        value: point.value,
      })),
    )
  }, [analysis.rsi])

  const overboughtData = useMemo(() => {
    return referenceLineData(analysis.candles.map((candle) => candle.date), 70)
  }, [analysis.candles])

  const oversoldData = useMemo(() => {
    return referenceLineData(analysis.candles.map((candle) => candle.date), 30)
  }, [analysis.candles])
  useEffect(() => {
    const container = containerRef.current

    if (!container) {
      return
    }

    const { chart, cleanup } = setupOptionsChart(container, { height: 180 })

    const rsi = chart.addSeries(LineSeries, {
      color: '#a78bfa',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    const overbought = chart.addSeries(LineSeries, {
      color: '#f97316',
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    const oversold = chart.addSeries(LineSeries, {
      color: '#22c55e',
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    rsi.setData(rsiData)
    overbought.setData(overboughtData)
    oversold.setData(oversoldData)
    chart.timeScale().fitContent()
    rsiRef.current = rsi
    overboughtRef.current = overbought
    oversoldRef.current = oversold
    onChartReady?.(chart)

    return () => {
      rsiRef.current = null
      overboughtRef.current = null
      oversoldRef.current = null
      onChartReady?.(null)
      cleanup()
    }
  }, [analysis.ticker, onChartReady, overboughtData, oversoldData, rsiData])

  useEffect(() => {
    if (!latestUpdate || latestUpdate.ticker !== analysis.ticker) {
      return
    }

    const { candle, rsi } = latestUpdate
    if (rsi.value !== null) {
      rsiRef.current?.update({ time: rsi.date, value: rsi.value })
    }
    overboughtRef.current?.update({ time: candle.date, value: 70 })
    oversoldRef.current?.update({ time: candle.date, value: 30 })
  }, [analysis.ticker, latestUpdate])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="flex items-baseline gap-2">
            <span>RSI</span>
            {currentRsi !== null ? (
              <span className="text-sm font-normal text-muted-foreground">
                {currentRsi.toFixed(2)}
              </span>
            ) : null}
          </span>
          <span className="text-sm font-normal text-muted-foreground">
            14-period
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          ref={containerRef}
          className="h-[180px] min-h-[160px] w-full overflow-hidden rounded-md border bg-background"
        />
      </CardContent>
    </Card>
  )
}
