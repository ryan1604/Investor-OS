import { apiUrl, apiWebSocketUrl, responseErrorMessage } from '@/api/client'

export type OrderAction = 'BUY' | 'SELL'
export type OrderTimeInForce = 'DAY' | 'GTC'
export type OrderType = 'MARKET' | 'LIMIT'
export type OrderStatus =
  | 'submitted'
  | 'working'
  | 'partially_filled'
  | 'filled'
  | 'cancelled'
  | 'rejected'
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

export type OptionStrategyLegRequest = {
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
  editable: boolean
  filled: number
  remaining: number | null
  avg_fill_price: number | null
  rejection_message: string | null
  submitted_at: string
  updated_at: string
  preview: OrderPreviewResponse
}

export type OrderSubmissionResponse = {
  order: OrderRecord
  message: string
}

export type OrderCancellationRequest = {
  account: string
}

export type OrderAmendmentRequest = {
  account: string
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
  const response = await fetch(apiUrl('/orders'))

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Order'))
  }

  return response.json() as Promise<OrderRecord[]>
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
  const response = await fetch(apiUrl(path), {
    method: options.method ?? 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, 'Order'))
  }

  return response.json() as Promise<Response>
}
