import { apiWebSocketUrl, jsonRequest, requestJson } from '@/api/client'

export type OrderAction = 'BUY' | 'SELL'
export type OrderTimeInForce = 'DAY' | 'GTC'
export type OrderType = 'MARKET' | 'LIMIT'
type OrderStatus =
  | 'submitted'
  | 'working'
  | 'partially_filled'
  | 'stale'
  | 'filled'
  | 'cancelled'
  | 'rejected'
type OrderReconciliationStatus = 'pending' | 'confirmed' | 'stale'
export type OptionRight = 'CALL' | 'PUT'

export type StockOrderRequest = {
  order_kind: 'stock'
  account: string
  ticker: string
  action: OrderAction
  quantity: number
  order_type?: OrderType
  limit_price?: number | null
  time_in_force?: OrderTimeInForce
}

type OptionStrategyLegRequest = {
  con_id?: number | null
  ticker: string
  expiration: string
  right: OptionRight
  strike: number
  action: OrderAction
  quantity: number
}

export type OptionStrategyOrderRequest = {
  order_kind: 'option_strategy'
  account: string
  legs: OptionStrategyLegRequest[]
  strategy_quantity?: number
  limit_price: number
  take_profit_price?: number | null
  stop_loss_price?: number | null
  time_in_force?: OrderTimeInForce
}

export type OrderPreviewableRequest =
  | StockOrderRequest
  | OptionStrategyOrderRequest

export type OrderPreviewResponse = {
  preview_id: string
  account: string
  order_kind: 'stock' | 'option_strategy'
  summary: string
  time_in_force: OrderTimeInForce
  estimated_order_type: string
  request: OrderPreviewableRequest
}

export type OrderRecord = {
  order_id: number
  perm_id: number | null
  parent_order_id: number | null
  account: string
  status: OrderStatus
  reconciliation_status: OrderReconciliationStatus
  editable: boolean
  read_only_reason?: string | null
  filled: number
  remaining: number | null
  avg_fill_price: number | null
  rejection_message: string | null
  execution_id?: string | null
  execution_ids?: string[]
  execution_time?: string | null
  execution_side?: string | null
  execution_quantity?: number | null
  execution_price?: number | null
  execution_cumulative_quantity?: number | null
  completed_time?: string | null
  completed_status?: string | null
  terminal_at?: string | null
  display_details?: string[]
  is_open: boolean
  is_current_day_history: boolean
  submitted_at: string
  updated_at: string
  preview: OrderPreviewResponse
}

type OrderSubmissionResponse = {
  order: OrderRecord
  message: string
}

type OrderCancellationRequest = {
  account: string
}

type OrderAmendmentRequest = {
  account: string
  quantity?: number | null
  limit_price?: number | null
  take_profit_price?: number | null
  stop_loss_price?: number | null
  time_in_force?: OrderTimeInForce | null
}

export type OrderStatusUpdate = {
  type: 'snapshot' | 'update'
  orders: OrderRecord[] | null
  order: OrderRecord | null
}

export const ORDERS_WS_URL = apiWebSocketUrl('/orders/ws')

export async function fetchOrders() {
  return requestJson<OrderRecord[]>('/orders', 'Order')
}

export async function previewOrder(request: OrderPreviewableRequest) {
  return postOrderRequest<OrderPreviewResponse>('/orders/preview', request)
}

export async function transmitOrder(request: OrderPreviewableRequest) {
  return postOrderRequest<OrderSubmissionResponse>('/orders/transmit', request)
}

export async function cancelOrder(
  orderId: number,
  request: OrderCancellationRequest,
) {
  return postOrderRequest<OrderSubmissionResponse>(
    `/orders/${orderId}/cancel`,
    request,
  )
}

export async function amendOrder(
  orderId: number,
  request: OrderAmendmentRequest,
) {
  return postOrderRequest<OrderSubmissionResponse>(`/orders/${orderId}`, request, {
    method: 'PATCH',
  })
}

async function postOrderRequest<Response>(
  path: string,
  body: OrderPreviewableRequest | OrderCancellationRequest | OrderAmendmentRequest,
  options: { method?: 'POST' | 'PATCH' } = {},
) {
  return jsonRequest<Response>(
    path,
    options.method ?? 'POST',
    body,
    'Order',
  )
}
