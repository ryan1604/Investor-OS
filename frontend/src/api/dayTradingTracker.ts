import {
  encodePathSegment,
  jsonRequest,
  requestJson,
} from '@/api/client'

export type DayTradingRow = {
  id: string
  display_order: number
  buy: number | null
  sell: number | null
  size: number | null
  fee: number | null
  created_at: string
  updated_at: string
}

export type DayTradingDay = {
  date: string
  trades: DayTradingRow[]
}

export type DayTradingMonthResponse = {
  month: string
  days: DayTradingDay[]
}

export type DayTradingRowRequest = {
  id?: string | null
  display_order: number
  buy?: number | null
  sell?: number | null
  size?: number | null
  fee?: number | null
}

export type DayTradingRowsReplaceRequest = {
  trades: DayTradingRowRequest[]
}

function dayTradingTrackerPath() {
  return '/day-trading-tracker'
}

export function dayTradingMonthPath(month: string) {
  return `${dayTradingTrackerPath()}/months/${encodePathSegment(
    month,
    'Month is required.',
  )}`
}

export function dayTradingDateTradesPath(date: string) {
  return `${dayTradingTrackerPath()}/days/${encodePathSegment(
    date,
    'Date is required.',
  )}/trades`
}

export async function fetchDayTradingMonth(month: string, signal?: AbortSignal) {
  return requestJson<DayTradingMonthResponse>(
    dayTradingMonthPath(month),
    'Day trading tracker',
    { signal },
  )
}

export async function replaceDayTradingDateTrades(
  date: string,
  request: DayTradingRowsReplaceRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<DayTradingDay>(
    dayTradingDateTradesPath(date),
    'PUT',
    request,
    'Day trading tracker',
    signal,
  )
}
