import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import {
  addEarningsWatchTickers,
  clearEarningsWatchReviews,
  fetchEarningsWatch,
  removeEarningsWatchTicker,
  setEarningsWatchReviewed,
  type EarningsWatchRefreshState,
  type EarningsWatchRow,
} from '@/api/earningsWatch'
import { errorMessage } from '@/lib/errors'
import {
  millisecondsUntil,
  millisecondsUntilNextNewYorkMidnight,
  nextSort,
  refreshMessage,
  safeErrorMessage,
  sortEarningsWatchRows,
  type EarningsWatchSort,
  type EarningsWatchSortKey,
} from '@/features/earnings-watch/lib/earningsWatch'

const defaultRefresh: EarningsWatchRefreshState = {
  state: 'never_attempted',
  last_attempt_at: null,
  last_success_at: null,
  last_success_date: null,
  error_category: null,
  next_eligible_retry_at: null,
}

const tickerTokenSeparator = /[,\s]+/
const tickerPattern = /^[A-Z0-9.-]+$/

export function useEarningsWatch() {
  const [rows, setRows] = useState<EarningsWatchRow[]>([])
  const [refresh, setRefresh] = useState<EarningsWatchRefreshState>(defaultRefresh)
  const [tickerInput, setTickerInput] = useState('')
  const [rejectedTokens, setRejectedTokens] = useState<string[]>([])
  const [warning, setWarning] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isAdding, setIsAdding] = useState(false)
  const [isClearing, setIsClearing] = useState(false)
  const [removingTicker, setRemovingTicker] = useState<string | null>(null)
  const [pendingReviewed, setPendingReviewed] = useState<Record<string, boolean>>({})
  const [focusedReviewedTicker, setFocusedReviewedTicker] = useState<string | null>(
    null,
  )
  const [deferredReviewedRows, setDeferredReviewedRows] = useState<
    EarningsWatchRow[] | null
  >(null)
  const [sort, setSort] = useState<EarningsWatchSort>({
    key: 'earnings_date',
    direction: 'asc',
  })
  const rowsRef = useRef(rows)
  const pendingReviewedRef = useRef(pendingReviewed)
  const pollingFailures = useRef(0)
  const tickerInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    rowsRef.current = rows
  }, [rows])

  useEffect(() => {
    pendingReviewedRef.current = pendingReviewed
  }, [pendingReviewed])

  const loadState = useCallback(async ({ quiet = false, polling = false } = {}) => {
    if (!quiet) {
      setIsLoading(true)
    }
    try {
      const response = await fetchEarningsWatch()
      setRows(
        mergeRowsPreservingPendingReviews(response.rows, pendingReviewedRef.current),
      )
      setRefresh(response.refresh)
      setWarning(null)
      pollingFailures.current = 0
    } catch (error) {
      if (polling) {
        pollingFailures.current += 1
        if (pollingFailures.current >= 3) {
          setWarning(errorMessage(error, 'Stopped polling earnings dates.'))
          setRefresh((current) => ({ ...current, state: 'failed' }))
        }
      } else {
        setWarning(errorMessage(error, 'Earnings Watch failed.'))
      }
    } finally {
      if (!quiet) {
        setIsLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void loadState()
    }, 0)
    return () => window.clearTimeout(timeout)
  }, [loadState])

  useEffect(() => {
    if (refresh.state !== 'refreshing') {
      return
    }
    const interval = window.setInterval(() => {
      void loadState({ quiet: true, polling: true })
    }, 2000)
    return () => window.clearInterval(interval)
  }, [loadState, refresh.state])

  useEffect(() => {
    if (refresh.state !== 'cooldown' || !refresh.next_eligible_retry_at) {
      return
    }
    const timeout = window.setTimeout(() => {
      void loadState({ quiet: true })
    }, millisecondsUntil(refresh.next_eligible_retry_at))
    return () => window.clearTimeout(timeout)
  }, [loadState, refresh.next_eligible_retry_at, refresh.state])

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void loadState({ quiet: true })
    }, millisecondsUntilNextNewYorkMidnight())
    return () => window.clearTimeout(timeout)
  }, [loadState])

  const sortedRows = useMemo(
    () => sortEarningsWatchRows(rows, sort),
    [rows, sort],
  )
  const displayRows =
    sort.key === 'reviewed' && focusedReviewedTicker && deferredReviewedRows
      ? deferredReviewedRows
      : sortedRows
  const hasReviewedRows = rows.some((row) => row.reviewed)
  const parsedInput = parseValidatedEarningsTickers(tickerInput)

  async function handleAddTickers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isAdding || parsedInput.valid.length === 0) {
      setRejectedTokens(parsedInput.rejected)
      return
    }

    const previousRows = rowsRef.current
    const now = new Date().toISOString()
    const existing = new Set(previousRows.map((row) => row.ticker))
    const optimisticRows = [
      ...previousRows,
      ...parsedInput.valid
        .filter((ticker) => !existing.has(ticker))
        .map((ticker) => emptyRow(ticker, now)),
    ]
    setRows(optimisticRows)
    setRejectedTokens(parsedInput.rejected)
    setIsAdding(true)
    try {
      const response = await addEarningsWatchTickers(tickerInput)
      setRows(response.rows)
      setRejectedTokens(response.rejected)
      setTickerInput('')
      setWarning(null)
    } catch (error) {
      setRows(previousRows)
      setWarning(errorMessage(error, 'Ticker add failed.'))
    } finally {
      setIsAdding(false)
      tickerInputRef.current?.focus()
    }
  }

  async function handleRemove(row: EarningsWatchRow) {
    if (removingTicker) {
      return
    }
    const previousRows = rowsRef.current
    setRows(previousRows.filter((current) => current.ticker !== row.ticker))
    setRemovingTicker(row.ticker)
    try {
      await removeEarningsWatchTicker(row.ticker)
      setWarning(null)
    } catch (error) {
      setRows(previousRows)
      setWarning(errorMessage(error, 'Ticker removal failed.'))
    } finally {
      setRemovingTicker(null)
    }
  }

  async function handleReviewedChange(row: EarningsWatchRow, reviewed: boolean) {
    const previousRows = rowsRef.current
    pendingReviewedRef.current = {
      ...pendingReviewedRef.current,
      [row.ticker]: reviewed,
    }
    setPendingReviewed(pendingReviewedRef.current)
    setRows((current) =>
      current.map((item) =>
        item.ticker === row.ticker ? { ...item, reviewed } : item,
      ),
    )
    try {
      const updatedRow = await setEarningsWatchReviewed(row.ticker, reviewed)
      setRows((current) =>
        current.map((item) => (item.ticker === row.ticker ? updatedRow : item)),
      )
      setWarning(null)
    } catch (error) {
      setRows(previousRows)
      setWarning(errorMessage(error, 'Review update failed.'))
    } finally {
      const rest = { ...pendingReviewedRef.current }
      delete rest[row.ticker]
      pendingReviewedRef.current = rest
      setPendingReviewed(rest)
    }
  }

  async function handleClearReviewed() {
    setIsClearing(true)
    try {
      const response = await clearEarningsWatchReviews()
      setRows(response.rows)
      setWarning(null)
    } catch (error) {
      setWarning(errorMessage(error, 'Clear reviewed failed.'))
    } finally {
      setIsClearing(false)
    }
  }

  function handleSort(key: EarningsWatchSortKey) {
    setSort((current) => nextSort(current, key))
  }

  const metadataMessage = refreshMessage(refresh)
  const refreshWarning =
    refresh.state === 'failed' || refresh.state === 'cooldown'
      ? safeErrorMessage(refresh.error_category)
      : null

  return {
    rows, refresh, tickerInput, setTickerInput, tickerInputRef, rejectedTokens,
    warning, isLoading, isAdding, isClearing, removingTicker, pendingReviewed,
    sort, displayRows, hasReviewedRows, parsedInput, metadataMessage, refreshWarning,
    setFocusedReviewedTicker, setDeferredReviewedRows,
    handleAddTickers, handleRemove, handleReviewedChange, handleClearReviewed, handleSort,
  }
}

function parseValidatedEarningsTickers(value: string) {
  const valid: string[] = []
  const rejected: string[] = []
  const seen = new Set<string>()
  for (const token of value.trim().split(tickerTokenSeparator)) {
    if (!token) {
      continue
    }
    const ticker = token.toUpperCase()
    if (!tickerPattern.test(ticker)) {
      rejected.push(token)
      continue
    }
    if (!seen.has(ticker)) {
      seen.add(ticker)
      valid.push(ticker)
    }
  }
  return { valid, rejected }
}

function emptyRow(ticker: string, timestamp: string): EarningsWatchRow {
  return {
    ticker,
    reviewed: false,
    earnings_date: null,
    status: 'no_date',
    created_at: timestamp,
    updated_at: timestamp,
  }
}

function mergeRowsPreservingPendingReviews(
  nextRows: EarningsWatchRow[],
  pendingReviewed: Record<string, boolean>,
) {
  return nextRows.map((row) =>
    row.ticker in pendingReviewed
      ? { ...row, reviewed: pendingReviewed[row.ticker] }
      : row,
  )
}
