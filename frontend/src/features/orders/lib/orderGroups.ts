import type { OrderRecord } from '@/api/orders'

export type OrderGroup = {
  groupId: number
  primary: OrderRecord
  children: OrderRecord[]
  records: OrderRecord[]
  readOnlyReason: string | null
}

export function formatQuantity(value: number) {
  return Number.isInteger(value) ? value.toFixed(0) : value.toString()
}

export function groupOrders(orders: OrderRecord[]): OrderGroup[] {
  const byId = new Map(orders.map((order) => [order.order_id, order]))
  const childIds = new Set(
    orders
      .filter((order) => order.parent_order_id !== null && byId.has(order.parent_order_id))
      .map((order) => order.order_id),
  )

  return orders
    .filter((order) => !childIds.has(order.order_id))
    .map((order) => {
      const children = orders
        .filter((child) => child.parent_order_id === order.order_id)
        .sort((left, right) => left.order_id - right.order_id)
      const records = [order, ...children]
      return {
        groupId: order.parent_order_id ?? order.order_id,
        primary: order,
        children,
        records,
        readOnlyReason: groupReadOnlyReason(order, records),
      }
    })
}

function groupReadOnlyReason(primary: OrderRecord, records: OrderRecord[]) {
  if (primary.parent_order_id !== null) {
    return 'Linked parent order is missing.'
  }
  if (records.some((record) => record.reconciliation_status === 'stale')) {
    return 'Order is not in the latest IB open-order snapshot.'
  }
  const readOnlyRecord = records.find((record) => record.editable === false)
  if (readOnlyRecord) {
    return readOnlyRecord.read_only_reason ?? 'Order is read-only.'
  }
  const request = primary.preview.request
  const needsLinkedOrders =
    request.order_kind === 'option_strategy' &&
    (request.take_profit_price != null || request.stop_loss_price != null)
  if (needsLinkedOrders && records.length === 1) {
    return 'Linked exit orders are incomplete.'
  }
  return null
}

export function modeledQuantity(order: OrderRecord) {
  const request = order.preview.request
  if (request.order_kind === 'stock') {
    return request.quantity
  }
  if (request.legs.length === 1) {
    return request.legs[0].quantity
  }
  return request.strategy_quantity ?? 1
}

export function linkedExitSummary(order: OrderRecord) {
  const request = order.preview.request
  if (request.order_kind !== 'option_strategy') {
    return 'Linked exits'
  }
  const exits = [
    request.take_profit_price ? `TP ${request.take_profit_price.toFixed(2)}` : null,
    request.stop_loss_price ? `SL ${request.stop_loss_price.toFixed(2)}` : null,
  ].filter(Boolean)
  return exits.length ? `Linked exits: ${exits.join(' | ')}` : 'Linked exits'
}
