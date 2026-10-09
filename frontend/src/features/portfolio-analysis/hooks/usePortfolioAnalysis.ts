import { useCallback, useEffect, useRef, useState } from 'react'

import {
  portfolioAnalysisWebSocketUrl,
  type PortfolioAnalysisResponse,
} from '@/api/portfolioAnalysis'
import { connectWithBackoff } from '@/lib/connectWithBackoff'

const DISCONNECTED_MESSAGE = 'Portfolio Analysis stream disconnected.'

// The socket holds the analysis feeds open only while the page is mounted.
export function usePortfolioAnalysis(account: string | null) {
  const [analysis, setAnalysis] = useState<PortfolioAnalysisResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const accountRef = useRef(account)
  const socketRef = useRef<WebSocket | null>(null)

  const requestAccount = useCallback(() => {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ account: accountRef.current ?? '' }))
    }
  }, [])

  useEffect(() => {
    accountRef.current = account
    requestAccount()
  }, [account, requestAccount])

  useEffect(() => {
    let hasSnapshot = false

    const disconnect = connectWithBackoff(
      () => portfolioAnalysisWebSocketUrl(accountRef.current),
      {
        onConnect: (socket) => {
          socketRef.current = socket
        },
        onMessage: (event) => {
          const next = JSON.parse(event.data) as PortfolioAnalysisResponse
          const requested = accountRef.current
          // Drop an update computed for the previous account before a switch landed.
          if (requested && next.accounts.includes(requested) && next.account !== requested) {
            return
          }
          hasSnapshot = true
          setAnalysis(next)
          setError(null)
          setIsLoading(false)
        },
        onClose: () => {
          setError(DISCONNECTED_MESSAGE)
          if (!hasSnapshot) {
            setIsLoading(false)
          }
        },
      },
    )

    return () => {
      disconnect()
      socketRef.current = null
    }
  }, [])

  return { analysis, isLoading, error, refresh: requestAccount }
}
