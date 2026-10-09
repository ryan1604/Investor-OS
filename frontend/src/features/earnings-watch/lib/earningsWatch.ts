import { newYorkDateParts } from '@/lib/dates'
import type { EarningsWatchRefreshState, EarningsWatchRow } from '@/api/earningsWatch'

export type EarningsWatchSortKey = 'ticker' | 'earnings_date' | 'status' | 'reviewed'
type EarningsWatchSortDirection = 'asc' | 'desc'

export type EarningsWatchSort = {
  key: EarningsWatchSortKey
  direction: EarningsWatchSortDirection
}

const statusRank = {
  upcoming: 0,
  last_known: 1,
  no_date: 2,
}

const statusLabels = {
  upcoming: 'Upcoming',
  last_known: 'Last known',
  no_date: 'No date',
}

const errorLabels: Record<string, string> = {
  not_configured: 'Alpha Vantage is not configured.',
  rate_limited: 'Alpha Vantage rate limit reached.',
  network: 'Network error while updating earnings dates.',
  timeout: 'Alpha Vantage request timed out.',
  invalid_response: 'Alpha Vantage returned an invalid calendar response.',
}

export function sortEarningsWatchRows(
  rows: EarningsWatchRow[],
  sort: EarningsWatchSort,
) {
  return [...rows].sort((left, right) => {
    if (sort.key === 'earnings_date') {
      const nullOrder = compareNullableDates(left, right)
      if (nullOrder !== 0) {
        return nullOrder
      }
    }
    const primary = compareRows(left, right, sort.key)
    const directed = sort.direction === 'asc' ? primary : -primary
    return directed || left.ticker.localeCompare(right.ticker)
  })
}

function compareNullableDates(left: EarningsWatchRow, right: EarningsWatchRow) {
  if (left.earnings_date === null && right.earnings_date === null) {
    return 0
  }
  if (left.earnings_date === null) {
    return 1
  }
  if (right.earnings_date === null) {
    return -1
  }
  return 0
}

function compareRows(
  left: EarningsWatchRow,
  right: EarningsWatchRow,
  key: EarningsWatchSortKey,
) {
  if (key === 'ticker') {
    return left.ticker.localeCompare(right.ticker)
  }
  if (key === 'status') {
    return statusRank[left.status] - statusRank[right.status]
  }
  if (key === 'reviewed') {
    return Number(left.reviewed) - Number(right.reviewed)
  }

  return compareNullableDates(left, right) ||
    (left.earnings_date ?? '').localeCompare(right.earnings_date ?? '')
}

export function nextSort(current: EarningsWatchSort, key: EarningsWatchSortKey) {
  if (current.key !== key) {
    return { key, direction: 'asc' } satisfies EarningsWatchSort
  }
  return {
    key,
    direction: current.direction === 'asc' ? 'desc' : 'asc',
  } satisfies EarningsWatchSort
}

export function formatEarningsDate(value: string | null) {
  if (value === null) {
    return '-'
  }
  const [year, month, day] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(year, month - 1, day))
}

export function statusLabel(status: EarningsWatchRow['status']) {
  return statusLabels[status]
}

export function refreshMessage(refresh: EarningsWatchRefreshState) {
  if (refresh.state === 'refreshing') {
    return 'Updating earnings dates...'
  }
  if (refresh.state === 'cooldown') {
    const retry = refresh.next_eligible_retry_at
      ? ` Next retry ${formatDateTime(refresh.next_eligible_retry_at)}.`
      : ''
    return `${safeErrorMessage(refresh.error_category)}${retry}`
  }
  if (refresh.state === 'failed') {
    return safeErrorMessage(refresh.error_category)
  }
  if (refresh.state === 'succeeded' && refresh.last_success_at) {
    return `Last updated ${formatDateTime(refresh.last_success_at)}.`
  }
  return null
}

export function safeErrorMessage(category: string | null) {
  return category ? (errorLabels[category] ?? 'Earnings dates are unavailable.') : null
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function millisecondsUntil(value: string, now = new Date()) {
  return Math.max(0, new Date(value).getTime() - now.getTime())
}

export function millisecondsUntilNextNewYorkMidnight(now = new Date()) {
  const timeZone = 'America/New_York'
  const parts = newYorkDateParts(now)
  const targetUtc = zonedDateTimeToUtc(
    timeZone,
    Number(parts.year),
    Number(parts.month),
    Number(parts.day) + 1,
  )
  return Math.max(60_000, targetUtc.getTime() - now.getTime())
}

function zonedDateTimeToUtc(
  timeZone: string,
  year: number,
  month: number,
  day: number,
) {
  const guess = new Date(Date.UTC(year, month - 1, day))
  const offset = timeZoneOffsetMilliseconds(timeZone, guess)
  return new Date(guess.getTime() - offset)
}

function timeZoneOffsetMilliseconds(timeZone: string, date: Date) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const parts = Object.fromEntries(
    formatter.formatToParts(date).map((part) => [part.type, part.value]),
  )
  return (
    Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    ) - date.getTime()
  )
}
