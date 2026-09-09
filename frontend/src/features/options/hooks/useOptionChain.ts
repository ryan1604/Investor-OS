import { useEffect, useState } from 'react'

import {
  getOptionChainWsUrl,
  type OptionChainLiveMessage,
  type OptionChainResponse,
  type OptionsAnalysisResponse,
} from '@/api/options'
import {
  mergeLiveChainRows,
  mergeLiveChainSnapshot,
} from '@/features/options/lib/chainRows'
import { hasAnalysisPriceData } from '@/features/options/hooks/useOptionsAnalysis'

export function useOptionChain(
  analysis: OptionsAnalysisResponse | null,
  selectedExpiration: string,
  isAnalysisLoading: boolean,
  isActive = true,
) {
  const [chain, setChain] = useState<OptionChainResponse | null>(null)
  const [chainError, setChainError] = useState<{
    key: string
    message: string
  } | null>(null)
  const activeTicker = analysis?.ticker ?? ''
  const canLoadChain =
    analysis !== null &&
    selectedExpiration !== '' &&
    hasAnalysisPriceData(analysis)
  const activeKey = `${activeTicker}\0${selectedExpiration}`

  useEffect(() => {
    if (!canLoadChain || !isActive) {
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
        setChainError(null)
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
        setChainError(null)
        pendingRows.push(message)
        scheduleFlush()
      }
    }

    socket.onerror = () => {
      setChainError({
        key: activeKey,
        message: 'Option chain stream disconnected.',
      })
    }

    return () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId)
      }
      socket.close()
    }
  }, [activeKey, activeTicker, canLoadChain, isActive, selectedExpiration])

  const activeChain =
    canLoadChain &&
    chain?.ticker === activeTicker &&
    chain.expiration === selectedExpiration
      ? chain
      : null

  return {
    chain: activeChain,
    chainError:
      canLoadChain && !isAnalysisLoading && chainError?.key === activeKey
        ? chainError.message
        : null,
    isChainLoading:
      canLoadChain && chainError?.key !== activeKey && activeChain === null,
  }
}
