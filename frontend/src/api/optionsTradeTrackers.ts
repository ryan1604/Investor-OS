import {
  encodePathSegment,
  jsonRequest,
  requestJson,
  requestOk,
} from '@/api/client'

export type OptionsTradeStatus = 'In Progress' | 'Completed'

export type OptionsTradeMonth =
  | 'jan'
  | 'feb'
  | 'mar'
  | 'apr'
  | 'may'
  | 'jun'
  | 'jul'
  | 'aug'
  | 'sep'
  | 'oct'
  | 'nov'
  | 'dec'

export type OptionsTradeTrackerSummary = {
  id: string
  name: string
  created_at: string
  updated_at: string
}

type OptionsTradeTrackerListResponse = {
  trackers: OptionsTradeTrackerSummary[]
}

export type OptionsTradeRow = {
  id: string
  display_order: number
  status: OptionsTradeStatus
  strategy: string | null
  ticker: string | null
  month: OptionsTradeMonth | null
  size: number | null
  strike_price: number | null
  credit_debit: number | null
  exit: number | null
  created_at: string
  updated_at: string
}

export type OptionsTradeRowRequest = {
  id?: string | null
  display_order: number
  status?: OptionsTradeStatus
  strategy?: string | null
  ticker?: string | null
  month?: OptionsTradeMonth | null
  size?: number | null
  strike_price?: number | null
  credit_debit?: number | null
  exit?: number | null
}

export type OptionsTradeTrackerDetailResponse = {
  tracker: OptionsTradeTrackerSummary
  trades: OptionsTradeRow[]
  notes: string
  strategy_options: string[]
}

type OptionsTradeTrackerCreateRequest = {
  name: string
}

type OptionsTradeTrackerRenameRequest = {
  name: string
}

type OptionsTradeRowsReplaceRequest = {
  trades: OptionsTradeRowRequest[]
}

type OptionsTradeNotesRequest = {
  notes: string
}

type OptionsTradeStrategiesRequest = {
  strategies: string[]
}

type OptionsTradeStrategyOptionsResponse = {
  strategies: string[]
}

function optionsTradeTrackersPath() {
  return '/options-trade-trackers'
}

function optionsTradeTrackerPath(trackerId: string) {
  return `${optionsTradeTrackersPath()}/${encodeTrackerId(trackerId)}`
}

function optionsTradeTrackerTradesPath(trackerId: string) {
  return `${optionsTradeTrackerPath(trackerId)}/trades`
}

function optionsTradeTrackerNotesPath(trackerId: string) {
  return `${optionsTradeTrackerPath(trackerId)}/notes`
}

function optionsTradeStrategyOptionsPath() {
  return `${optionsTradeTrackersPath()}/strategy-options`
}

export async function fetchOptionsTradeTrackers(signal?: AbortSignal) {
  return requestJson<OptionsTradeTrackerListResponse>(
    optionsTradeTrackersPath(),
    'Options trade trackers',
    { signal },
  )
}

export async function createOptionsTradeTracker(
  request: OptionsTradeTrackerCreateRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsTradeTrackerDetailResponse>(
    optionsTradeTrackersPath(),
    'POST',
    request,
    'Options trade tracker',
    signal,
  )
}

export async function fetchOptionsTradeTracker(
  trackerId: string,
  signal?: AbortSignal,
) {
  return requestJson<OptionsTradeTrackerDetailResponse>(
    optionsTradeTrackerPath(trackerId),
    'Options trade tracker',
    { signal },
  )
}

export async function renameOptionsTradeTracker(
  trackerId: string,
  request: OptionsTradeTrackerRenameRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsTradeTrackerDetailResponse>(
    optionsTradeTrackerPath(trackerId),
    'PATCH',
    request,
    'Options trade tracker',
    signal,
  )
}

export async function deleteOptionsTradeTracker(
  trackerId: string,
  signal?: AbortSignal,
) {
  await requestOk(optionsTradeTrackerPath(trackerId), 'Options trade tracker', {
    method: 'DELETE',
    signal,
  })
}

export async function replaceOptionsTradeTrackerTrades(
  trackerId: string,
  request: OptionsTradeRowsReplaceRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsTradeTrackerDetailResponse>(
    optionsTradeTrackerTradesPath(trackerId),
    'PUT',
    request,
    'Options trade tracker',
    signal,
  )
}

export async function updateOptionsTradeTrackerNotes(
  trackerId: string,
  request: OptionsTradeNotesRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsTradeTrackerDetailResponse>(
    optionsTradeTrackerNotesPath(trackerId),
    'PUT',
    request,
    'Options trade tracker',
    signal,
  )
}

export async function fetchOptionsTradeStrategyOptions(signal?: AbortSignal) {
  return requestJson<OptionsTradeStrategyOptionsResponse>(
    optionsTradeStrategyOptionsPath(),
    'Options trade strategy options',
    { signal },
  )
}

export async function replaceOptionsTradeStrategyOptions(
  request: OptionsTradeStrategiesRequest,
  signal?: AbortSignal,
) {
  return jsonRequest<OptionsTradeStrategyOptionsResponse>(
    optionsTradeStrategyOptionsPath(),
    'PUT',
    request,
    'Options trade tracker',
    signal,
  )
}

function encodeTrackerId(trackerId: string) {
  return encodePathSegment(trackerId, 'Tracker id is required.')
}
