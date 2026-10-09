const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 10_000

type ConnectionHandlers = {
  onConnect?: (socket: WebSocket) => void
  onMessage?: (event: MessageEvent) => void
  onError?: () => void
  onClose?: () => void
}

export function connectWithBackoff(
  url: string | (() => string),
  handlers: ConnectionHandlers = {},
) {
  let ignore = false
  let reconnectDelay = INITIAL_RECONNECT_DELAY_MS
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let socket: WebSocket | null = null

  const connect = () => {
    socket = new WebSocket(typeof url === 'function' ? url() : url)
    handlers.onConnect?.(socket)

    socket.onopen = () => {
      reconnectDelay = INITIAL_RECONNECT_DELAY_MS
    }

    if (handlers.onMessage) {
      socket.onmessage = (event) => {
        if (!ignore) {
          handlers.onMessage?.(event)
        }
      }
    }

    if (handlers.onError) {
      socket.onerror = () => {
        if (!ignore) {
          handlers.onError?.()
        }
      }
    }

    socket.onclose = () => {
      if (ignore) {
        return
      }

      handlers.onClose?.()
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
}
