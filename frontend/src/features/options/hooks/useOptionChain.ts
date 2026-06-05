import { useEffect, useState } from 'react'

import {
  fetchOptionChain,
  getOptionChainWsUrl,
  type OptionChainLiveMessage,
  type OptionChainResponse,
  type OptionsAnalysisResponse,
} from '@/api/options'
import { isAbortError } from '@/api/client'
import {
  mergeLiveChainRows,
  mergeLiveChainSnapshot,
} from '@/features/options/lib/chainRows'
import {
  errorMessage,
  hasAnalysisPriceData,
} from '@/features/options/hooks/useOptionsAnalysis'

export function useOptionChain(
  analysis: OptionsAnalysisResponse | null,
  selectedExpiration: string,
  isAnalysisLoading: boolean,
) {
  const [chain, setChain] = useState<OptionChainResponse | null>(null)
  const [isChainLoading, setIsChainLoading] = useState(false)
  const [chainError, setChainError] = useState<string | null>(null)
  const activeTicker = analysis?.ticker ?? ''
  const canLoadChain =
    analysis !== null &&
    selectedExpiration !== '' &&
    hasAnalysisPriceData(analysis)

  useEffect(() => {
    if (!canLoadChain) {
      return
    }

    let isStale = false
    const activeExpiration = selectedExpiration
    const requestController = new AbortController()

    async function loadChain() {
      setIsChainLoading(true)
      setChainError(null)

      try {
        const nextChain = await fetchOptionChain(
          activeTicker,
          activeExpiration,
          requestController.signal,
        )

        if (!isStale) {
          setChain(nextChain)
        }
      } catch (nextError) {
        if (isAbortError(nextError)) {
          return
        }

        if (!isStale) {
          setChain(null)
          setChainError(errorMessage(nextError))
        }
      } finally {
        if (!isStale) {
          setIsChainLoading(false)
        }
      }
    }

    void loadChain()

    return () => {
      isStale = true
      requestController.abort()
    }
  }, [activeTicker, canLoadChain, selectedExpiration])

  useEffect(() => {
    if (!canLoadChain) {
      return
    }

    const socket = new WebSocket(
      getOptionChainWsUrl(activeTicker, selectedExpiration),
    )
    const activeExpiration = selectedExpiration
    let pendingRows: OptionChainLiveMessage[] = []
    let frameId: number | null = null

    const scheduleFlush = () => {
      if (frameId !== null) {
        return
      }

      frameId = requestAnimationFrame(() => {
        frameId = null
        const messages = pendingRows
        pendingRows = []
        const rows = messages
          .map((message) => message.row)
          .filter((row): row is NonNullable<typeof row> => row !== undefined)
        const message = messages.at(-1)?.message ?? null

        if (!rows.length) {
          return
        }

        setChain((currentChain) =>
          mergeLiveChainRows(
            currentChain,
            activeTicker,
            activeExpiration,
            rows,
            message,
          ),
        )
      })
    }

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data as string) as OptionChainLiveMessage

      if (
        message.ticker !== activeTicker ||
        message.expiration !== activeExpiration
      ) {
        return
      }

      if (message.type === 'snapshot' && message.rows) {
        pendingRows = []
        if (frameId !== null) {
          cancelAnimationFrame(frameId)
          frameId = null
        }
        setChain((currentChain) =>
          mergeLiveChainSnapshot(
            currentChain,
            activeTicker,
            activeExpiration,
            message.rows ?? [],
            message.message ?? null,
          ),
        )
        return
      }

      if (message.type === 'update' && message.row) {
        pendingRows.push(message)
        scheduleFlush()
      }
    }

    socket.onerror = () => {
      setChainError('Option chain stream disconnected.')
    }

    return () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId)
      }
      socket.close()
    }
  }, [activeTicker, canLoadChain, selectedExpiration])

  const activeChain =
    canLoadChain &&
    chain?.ticker === activeTicker &&
    chain.expiration === selectedExpiration
      ? chain
      : null

  return {
    chain: activeChain,
    chainError: canLoadChain && !isAnalysisLoading ? chainError : null,
    isChainLoading: canLoadChain ? isChainLoading : false,
  }
}
