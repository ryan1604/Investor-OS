import { useEffect, useMemo, useRef } from 'react'

import {
  CandlestickSeries,
  LineSeries,
  LineStyle,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts'

import type {
  OptionsAnalysisResponse,
  OptionsChartLiveMessage,
} from '@/api/options'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  nullableLineData,
  setupOptionsChart,
} from '@/features/options/lib/chartHelpers'
import type {
  ChartOptionOverlaySource,
  ChartOverlay,
} from '@/features/options/lib/chartOverlays'

type OptionsChartProps = {
  analysis: OptionsAnalysisResponse
  latestUpdate: OptionsChartLiveMessage | null
  overlays?: ChartOverlay[]
  onChartReady?: (chart: IChartApi | null) => void
}

export function OptionsChart({
  analysis,
  latestUpdate,
  overlays = [],
  onChartReady,
}: OptionsChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const upperBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const middleBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const lowerBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const overlayLinesRef = useRef<Map<string, IPriceLine>>(new Map())

  const currentBands = useMemo(() => {
    if (
      latestUpdate?.ticker === analysis.ticker &&
      latestUpdate.bollinger_band.lower !== null &&
      latestUpdate.bollinger_band.middle !== null &&
      latestUpdate.bollinger_band.upper !== null
    ) {
      return latestUpdate.bollinger_band
    }

    return [...analysis.bollinger_bands]
      .reverse()
      .find(
        (point) =>
          point.lower !== null && point.middle !== null && point.upper !== null,
      ) ?? null
  }, [analysis.bollinger_bands, analysis.ticker, latestUpdate])

  const candleData = useMemo<CandlestickData<Time>[]>(() => {
    return analysis.candles.map((candle) => ({
      time: candle.date,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }))
  }, [analysis.candles])

  const upperBandData = useMemo(() => {
    return nullableLineData(
      analysis.bollinger_bands.map((point) => ({
        time: point.date,
        value: point.upper,
      })),
    )
  }, [analysis.bollinger_bands])

  const middleBandData = useMemo(() => {
    return nullableLineData(
      analysis.bollinger_bands.map((point) => ({
        time: point.date,
        value: point.middle,
      })),
    )
  }, [analysis.bollinger_bands])

  const lowerBandData = useMemo(() => {
    return nullableLineData(
      analysis.bollinger_bands.map((point) => ({
        time: point.date,
        value: point.lower,
      })),
    )
  }, [analysis.bollinger_bands])
  useEffect(() => {
    const container = containerRef.current

    if (!container) {
      return
    }

    const { chart, cleanup } = setupOptionsChart(container, {
      height: 420,
      timeVisible: false,
    })

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#86efac',
      wickDownColor: '#fca5a5',
    })
    const upperBand = chart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    const middleBand = chart.addSeries(LineSeries, {
      color: '#eab308',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    const lowerBand = chart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    candles.setData(candleData)
    upperBand.setData(upperBandData)
    middleBand.setData(middleBandData)
    lowerBand.setData(lowerBandData)
    chart.timeScale().fitContent()
    const overlayLines = overlayLinesRef.current
    candlesRef.current = candles
    upperBandRef.current = upperBand
    middleBandRef.current = middleBand
    lowerBandRef.current = lowerBand
    onChartReady?.(chart)

    return () => {
      candlesRef.current = null
      upperBandRef.current = null
      middleBandRef.current = null
      lowerBandRef.current = null
      overlayLines.clear()
      onChartReady?.(null)
      cleanup()
    }
  }, [
    analysis.ticker,
    candleData,
    lowerBandData,
    middleBandData,
    onChartReady,
    upperBandData,
  ])

  useEffect(() => {
    if (!latestUpdate || latestUpdate.ticker !== analysis.ticker) {
      return
    }

    candlesRef.current?.update({
      time: latestUpdate.candle.date,
      open: latestUpdate.candle.open,
      high: latestUpdate.candle.high,
      low: latestUpdate.candle.low,
      close: latestUpdate.candle.close,
    })

    const band = latestUpdate.bollinger_band
    if (band.upper !== null) {
      upperBandRef.current?.update({ time: band.date, value: band.upper })
    }
    if (band.middle !== null) {
      middleBandRef.current?.update({ time: band.date, value: band.middle })
    }
    if (band.lower !== null) {
      lowerBandRef.current?.update({ time: band.date, value: band.lower })
    }
  }, [analysis.ticker, latestUpdate])

  useEffect(() => {
    const candles = candlesRef.current
    if (!candles) {
      return
    }

    const nextKeys = new Set(overlays.map((overlay) => overlay.key))
    for (const [key, line] of overlayLinesRef.current) {
      if (!nextKeys.has(key)) {
        candles.removePriceLine(line)
        overlayLinesRef.current.delete(key)
      }
    }

    for (const overlay of overlays) {
      const options = overlayPriceLineOptions(overlay)
      const existingLine = overlayLinesRef.current.get(overlay.key)

      if (existingLine) {
        existingLine.applyOptions(options)
        continue
      }

      overlayLinesRef.current.set(overlay.key, candles.createPriceLine(options))
    }
  }, [overlays])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="flex flex-col gap-1">
            <span>{analysis.ticker} Daily</span>
            {currentBands ? (
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm font-normal text-muted-foreground">
                <span>LOWER: {currentBands.lower?.toFixed(2)}</span>
                <span>MID: {currentBands.middle?.toFixed(2)}</span>
                <span>UPPER: {currentBands.upper?.toFixed(2)}</span>
              </span>
            ) : null}
          </span>
          <span className="text-sm font-normal text-muted-foreground">
            {analysis.candles.length +
              (latestUpdate?.ticker === analysis.ticker &&
              !analysis.candles.some(
                (candle) => candle.date === latestUpdate.candle.date,
              )
                ? 1
                : 0)} candles
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          ref={containerRef}
          className="h-[420px] min-h-[320px] w-full overflow-hidden rounded-md border bg-background"
        />
      </CardContent>
    </Card>
  )
}

function overlayPriceLineOptions(overlay: ChartOverlay) {
  if (overlay.type === 'stock-cost-basis') {
    return {
      price: overlay.price,
      color: '#ffffff',
      lineWidth: 1 as const,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: overlay.label,
    }
  }

  return {
    price: overlay.strike,
    color: overlay.right === 'CALL' ? '#22c55e' : '#ef4444',
    lineWidth: optionOverlayLineWidth(overlay.sources),
    lineStyle: LineStyle.Dashed,
    axisLabelVisible: true,
    title: `${overlay.label} ${overlaySourceLabel(overlay.sources)}`,
  }
}

function optionOverlayLineWidth(sources: ChartOptionOverlaySource[]) {
  if (sources.includes('held')) {
    return 3 as const
  }
  if (sources.includes('working')) {
    return 2 as const
  }
  return 1 as const
}

function overlaySourceLabel(sources: ChartOptionOverlaySource[]) {
  return sources
    .map((source) =>
      source === 'draft' ? 'draft' : source === 'working' ? 'working' : 'held',
    )
    .join('/')
}
