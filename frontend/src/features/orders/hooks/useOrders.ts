import { useEffect, useState } from 'react'

import {
  ORDERS_WS_URL,
  fetchOrders,
  type OrderRecord,
  type OrderStatusUpdate,
} from '@/api/orders'
import { errorMessage } from '@/lib/errors'
import { connectWithBackoff } from '@/lib/connectWithBackoff'

export function useOrders(isEnabled = true) {
  const [orders, setOrders] = useState<OrderRecord[]>([])
  const [warning, setWarning] = useState<string | null>(null)

  useEffect(() => {
    if (!isEnabled) {
      return
    }

    let ignore = false
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

    const disconnect = connectWithBackoff(ORDERS_WS_URL, {
      onMessage: (event) => {
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
      },
    })

    return () => {
      ignore = true
      disconnect()
    }
  }, [isEnabled])

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
