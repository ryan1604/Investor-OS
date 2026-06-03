import { useEffect, useState } from 'react'

import {
  fetchOptionChain,
  getOptionChainWsUrl,
  type OptionChainLiveMessage,
  type OptionChainResponse,
  type OptionsAnalysisResponse,
} from '@/api/options'
import {
  mergeLiveChainRow,
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

    async function loadChain() {
      setIsChainLoading(true)
      setChainError(null)

      try {
        const nextChain = await fetchOptionChain(
          activeTicker,
          activeExpiration,
        )

        if (!isStale) {
          setChain(nextChain)
        }
      } catch (nextError) {
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

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data as string) as OptionChainLiveMessage

      if (
        message.ticker !== activeTicker ||
        message.expiration !== activeExpiration
      ) {
        return
      }

      if (message.type === 'snapshot' && message.rows) {
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
        const liveRow = message.row
        setChain((currentChain) =>
          mergeLiveChainRow(
            currentChain,
            activeTicker,
            activeExpiration,
            liveRow,
            message.message ?? null,
          ),
        )
      }
    }

    socket.onerror = () => {
      setChainError('Option chain stream disconnected.')
    }

    return () => {
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
