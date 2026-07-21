import { useCallback, useEffect, useRef, useState } from 'react'

import {
  PORTFOLIO_WS_URL,
  fetchPortfolio,
  type PortfolioResponse,
} from '@/api/portfolio'
import { errorMessage } from '@/api/client'

const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 10_000

function portfolioErrorMessage(error: unknown) {
  return errorMessage(error, 'Portfolio request failed')
}

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const isRequestInFlight = useRef(false)

  const loadPortfolio = useCallback(async () => {
    if (isRequestInFlight.current) {
      return
    }

    isRequestInFlight.current = true
    setIsLoading(true)
    setError(null)

    try {
      setPortfolio(await fetchPortfolio())
    } catch (requestError) {
      setError(portfolioErrorMessage(requestError))
    } finally {
      isRequestInFlight.current = false
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let ignore = false
    let reconnectDelay = INITIAL_RECONNECT_DELAY_MS
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let socket: WebSocket | null = null
    let hasSnapshot = false

    const connect = () => {
      socket = new WebSocket(PORTFOLIO_WS_URL)

      socket.onopen = () => {
        reconnectDelay = INITIAL_RECONNECT_DELAY_MS
      }

      socket.onmessage = (event) => {
        if (ignore) {
          return
        }

        hasSnapshot = true
        setPortfolio(JSON.parse(event.data) as PortfolioResponse)
        setError(null)
        setIsLoading(false)
      }

      socket.onerror = () => {
        if (!ignore) {
          setError('Portfolio stream disconnected.')
          if (!hasSnapshot) {
            setIsLoading(false)
          }
        }
      }

      socket.onclose = () => {
        if (ignore) {
          return
        }

        setError('Portfolio stream disconnected.')
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
      socket?.close()
    }
  }, [])

  return {
    portfolio,
    isLoading,
    error,
    loadPortfolio,
  }
}
