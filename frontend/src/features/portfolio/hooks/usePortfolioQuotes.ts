import { useEffect } from 'react'

import { PORTFOLIO_QUOTES_WS_URL } from '@/api/portfolio'

const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 10_000

// Holds IB position quotes open only while the Portfolio page is mounted,
// so their market-data lines are free for other pages otherwise.
export function usePortfolioQuotes() {
  useEffect(() => {
    let ignore = false
    let reconnectDelay = INITIAL_RECONNECT_DELAY_MS
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let socket: WebSocket | null = null

    const connect = () => {
      socket = new WebSocket(PORTFOLIO_QUOTES_WS_URL)

      socket.onopen = () => {
        reconnectDelay = INITIAL_RECONNECT_DELAY_MS
      }

      socket.onclose = () => {
        if (ignore) {
          return
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
}
