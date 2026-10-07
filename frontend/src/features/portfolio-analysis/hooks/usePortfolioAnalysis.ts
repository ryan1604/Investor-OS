import { useCallback, useEffect, useRef, useState } from 'react'

import {
  portfolioAnalysisWebSocketUrl,
  type PortfolioAnalysisResponse,
} from '@/api/portfolioAnalysis'

const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 10_000
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
    let ignore = false
    let reconnectDelay = INITIAL_RECONNECT_DELAY_MS
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let hasSnapshot = false

    const connect = () => {
      const socket = new WebSocket(portfolioAnalysisWebSocketUrl(accountRef.current))
      socketRef.current = socket

      socket.onopen = () => {
        reconnectDelay = INITIAL_RECONNECT_DELAY_MS
      }

      socket.onmessage = (event) => {
        if (ignore) {
          return
        }

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
      }

      socket.onclose = () => {
        if (ignore) {
          return
        }

        setError(DISCONNECTED_MESSAGE)
        if (!hasSnapshot) {
          setIsLoading(false)
        }
        reconnectTimer = setTimeout(connect, reconnectDelay)
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS)
      }
    }

    connect()

    return () => {
      ignore = true
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer)
      }
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [])

  return { analysis, isLoading, error, refresh: requestAccount }
}
