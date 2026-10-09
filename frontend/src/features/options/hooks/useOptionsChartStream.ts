import { useEffect, useState } from 'react'

import {
  getOptionsChartWsUrl,
  type OptionsAnalysisResponse,
  type OptionsChartLiveMessage,
} from '@/api/options'

export function useOptionsChartStream(
  analysis: OptionsAnalysisResponse | null,
  isActive = true,
) {
  const [liveState, setLiveState] = useState<{
    baseline: OptionsAnalysisResponse
    latestUpdate: OptionsChartLiveMessage
  } | null>(null)
  const [error, setError] = useState<{ ticker: string; message: string } | null>(
    null,
  )

  useEffect(() => {
    if (!analysis || !isActive) {
      return
    }

    const activeTicker = analysis.ticker
    const socket = new WebSocket(getOptionsChartWsUrl(activeTicker))
    let isCleaningUp = false

    socket.onmessage = (event) => {
      const update = JSON.parse(event.data as string) as OptionsChartLiveMessage
      if (
        update.ticker !== activeTicker ||
        isOlderThanLatestCandle(analysis, update)
      ) {
        return
      }

      setLiveState({
        baseline: analysis,
        latestUpdate: update,
      })
      setError(null)
    }

    const handleDisconnect = () => {
      if (isCleaningUp) {
        return
      }

      setError({
        ticker: activeTicker,
        message: 'Options chart stream disconnected.',
      })
    }

    socket.onerror = handleDisconnect
    socket.onclose = handleDisconnect

    return () => {
      isCleaningUp = true
      socket.close()
    }
  }, [analysis, isActive])

  const activeLiveState = liveState?.baseline === analysis ? liveState : null
  const liveAnalysis: OptionsAnalysisResponse | null = analysis && activeLiveState
    ? {
        ...analysis,
        underlying_price: activeLiveState.latestUpdate.candle.close,
      }
    : analysis

  return {
    analysis: liveAnalysis,
    error: error?.ticker === analysis?.ticker ? (error?.message ?? null) : null,
    latestUpdate: activeLiveState?.latestUpdate ?? null,
  }
}

function isOlderThanLatestCandle(
  analysis: OptionsAnalysisResponse,
  update: OptionsChartLiveMessage,
) {
  const latestCandle = analysis.candles.at(-1)
  return latestCandle ? update.candle.date < latestCandle.date : false
}
