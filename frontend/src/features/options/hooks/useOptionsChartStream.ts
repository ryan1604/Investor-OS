import { useEffect, useState } from 'react'

import {
  getOptionsChartWsUrl,
  type OptionsAnalysisResponse,
  type OptionsChartLiveMessage,
} from '@/api/options'

export function useOptionsChartStream(
  analysis: OptionsAnalysisResponse | null,
) {
  const [liveAnalysis, setLiveAnalysis] =
    useState<OptionsAnalysisResponse | null>(null)
  const [latestUpdate, setLatestUpdate] =
    useState<OptionsChartLiveMessage | null>(null)
  const [error, setError] = useState<{ ticker: string; message: string } | null>(
    null,
  )

  useEffect(() => {
    if (!analysis) {
      return
    }

    const activeTicker = analysis.ticker
    const socket = new WebSocket(getOptionsChartWsUrl(activeTicker))

    socket.onmessage = (event) => {
      const update = JSON.parse(event.data as string) as OptionsChartLiveMessage
      if (
        update.ticker !== activeTicker ||
        isOlderThanLatestCandle(analysis, update)
      ) {
        return
      }

      setLatestUpdate(update)
      setLiveAnalysis((currentAnalysis) =>
        currentAnalysis?.ticker === activeTicker
          ? mergeOptionsChartUpdate(currentAnalysis, update)
          : mergeOptionsChartUpdate(analysis, update),
      )
      setError(null)
    }

    socket.onerror = () => {
      setError({
        ticker: activeTicker,
        message: 'Options chart stream disconnected.',
      })
    }

    socket.onclose = () => {
      setError({
        ticker: activeTicker,
        message: 'Options chart stream disconnected.',
      })
    }

    return () => {
      socket.close()
    }
  }, [analysis])

  return {
    analysis:
      liveAnalysis?.ticker === analysis?.ticker ? liveAnalysis : analysis,
    error: error?.ticker === analysis?.ticker ? (error?.message ?? null) : null,
    latestUpdate:
      latestUpdate?.ticker === analysis?.ticker ? latestUpdate : null,
  }
}

function isOlderThanLatestCandle(
  analysis: OptionsAnalysisResponse,
  update: OptionsChartLiveMessage,
) {
  const latestCandle = analysis.candles.at(-1)
  return latestCandle ? update.candle.date < latestCandle.date : false
}

export function mergeOptionsChartUpdate(
  analysis: OptionsAnalysisResponse,
  update: OptionsChartLiveMessage,
): OptionsAnalysisResponse {
  return {
    ...analysis,
    underlying_price: update.candle.close,
    candles: replaceDatedPoint(analysis.candles, update.candle),
    bollinger_bands: replaceDatedPoint(
      analysis.bollinger_bands,
      update.bollinger_band,
    ),
    rsi: replaceDatedPoint(analysis.rsi, update.rsi),
  }
}

function replaceDatedPoint<T extends { date: string }>(
  points: T[],
  update: T,
) {
  const existingIndex = points.findIndex((point) => point.date === update.date)
  if (existingIndex === -1) {
    return [...points, update]
  }

  return points.map((point, index) => (index === existingIndex ? update : point))
}
