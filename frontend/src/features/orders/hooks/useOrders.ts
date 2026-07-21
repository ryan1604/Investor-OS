import { useEffect, useState } from 'react'

import {
  ORDERS_WS_URL,
  fetchOrders,
  type OrderRecord,
  type OrderStatusUpdate,
} from '@/api/orders'
import { errorMessage } from '@/api/client'

const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 10_000

export function useOrders() {
  const [orders, setOrders] = useState<OrderRecord[]>([])
  const [warning, setWarning] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    let reconnectDelay = INITIAL_RECONNECT_DELAY_MS
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let socket: WebSocket | null = null
    let hasStreamUpdate = false

    void fetchOrders()
      .then((snapshot) => {
        if (!ignore && !hasStreamUpdate) {
          setOrders(snapshot)
          setWarning(null)
        }
      })
      .catch((error) => {
        if (!ignore) {
          setWarning(errorMessage(error, 'Order load failed.'))
        }
      })

    const connect = () => {
      socket = new WebSocket(ORDERS_WS_URL)

      socket.onopen = () => {
        reconnectDelay = INITIAL_RECONNECT_DELAY_MS
      }

      socket.onmessage = (event) => {
        if (ignore) {
          return
        }

        const update = JSON.parse(event.data as string) as OrderStatusUpdate
        hasStreamUpdate = true
        if (update.type === 'snapshot') {
          setOrders(update.orders ?? [])
          setWarning(null)
          return
        }
        const order = update.order
        if (order) {
          setOrders((currentOrders) => upsertOrder(currentOrders, order))
          setWarning(null)
        }
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

  return { orders, warning }
}

function upsertOrder(orders: OrderRecord[], order: OrderRecord) {
  const existingIndex = orders.findIndex(
    (currentOrder) =>
      currentOrder.order_id === order.order_id ||
      (order.perm_id !== null && currentOrder.perm_id === order.perm_id),
  )
  if (existingIndex < 0) {
    return [...orders, order]
  }

  const withoutDuplicatePermId = orders.filter(
    (currentOrder, index) =>
      index === existingIndex ||
      order.perm_id === null ||
      currentOrder.perm_id !== order.perm_id,
  )
  return withoutDuplicatePermId.map((currentOrder, index) =>
    index === existingIndex ? order : currentOrder,
  )
}
