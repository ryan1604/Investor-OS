import { useEffect, useMemo, useRef, useState } from 'react'

import { fetchDayTradingMonth, replaceDayTradingDateTrades } from '@/api/dayTradingTracker'
import { isAbortError } from '@/api/client'
import { createLocalId } from '@/lib/drafts'
import { errorMessage } from '@/lib/errors'
import {
  buildMonthWeeks,
  calculateDayTradingStats,
  calculateMonthlyDayTradingStats,
  currentIsoDate,
  draftRowsFromStoredRows,
  initialMonth,
  newDayTradeDraftRow,
  requestRowsFromDraftRows,
  validateDayTradeDraftRows,
  type DayTradeDraftField,
  type DayTradeDraftIssue,
  type DayTradeDraftRow,
} from '@/features/day-trading-tracker/lib/dayTradingTracker'

type SaveStatus = 'idle' | 'loading' | 'saving' | 'saved' | 'error'

export function useDayTradingMonth() {
  const today = useMemo(() => currentIsoDate(), [])
  const [month, setMonth] = useState(() => initialMonth(today))
  const [openDate, setOpenDate] = useState<string | null>(null)
  const [draftRowsByDate, setDraftRowsByDate] = useState<
    Record<string, DayTradeDraftRow[]>
  >({})
  const [dirtyDates, setDirtyDates] = useState<Set<string>>(() => new Set())
  const dirtyDatesRef = useRef(dirtyDates)
  const [issuesByDate, setIssuesByDate] = useState<
    Record<string, DayTradeDraftIssue[]>
  >({})
  const [status, setStatus] = useState<SaveStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    dirtyDatesRef.current = dirtyDates
  }, [dirtyDates])

  useEffect(() => {
    const controller = new AbortController()

    async function loadMonth() {
      setStatus('loading')
      setError(null)

      try {
        const response = await fetchDayTradingMonth(month, controller.signal)
        if (controller.signal.aborted) {
          return
        }

        const loadedRowsByDate = Object.fromEntries(
          response.days.map((day) => [
            day.date,
            draftRowsFromStoredRows(day.trades),
          ]),
        )
        setDraftRowsByDate((current) => {
          const next = { ...current }

          Object.entries(loadedRowsByDate).forEach(([date, rows]) => {
            if (!dirtyDatesRef.current.has(date)) {
              next[date] = rows
            }
          })

          return next
        })
        setStatus('idle')
      } catch (requestError) {
        if (!isAbortError(requestError)) {
          setStatus('error')
          setError(errorMessage(requestError, 'Day trading tracker request failed.'))
        }
      }
    }

    void loadMonth()

    return () => {
      controller.abort()
    }
  }, [month])

  const weeks = useMemo(() => buildMonthWeeks(month, today), [month, today])
  const visibleRowsByDate = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(draftRowsByDate).filter(([date]) =>
          date.startsWith(`${month}-`),
        ),
      ),
    [draftRowsByDate, month],
  )
  const monthlyStats = useMemo(
    () => calculateMonthlyDayTradingStats(visibleRowsByDate),
    [visibleRowsByDate],
  )
  const selectedRows = openDate ? draftRowsByDate[openDate] ?? [] : []
  const selectedIssues = openDate ? issuesByDate[openDate] ?? [] : []
  const selectedStats = calculateDayTradingStats(selectedRows)

  async function saveSelectedDate() {
    if (!openDate) {
      return
    }

    const issues = validateDayTradeDraftRows(selectedRows)
    setIssuesByDate((current) => ({ ...current, [openDate]: issues }))
    if (issues.length > 0) {
      setError('Resolve day trade validation before saving.')
      setStatus('error')
      return
    }

    setStatus('saving')
    setError(null)

    try {
      const savedDay = await replaceDayTradingDateTrades(openDate, {
        trades: requestRowsFromDraftRows(selectedRows),
      })
      setDraftRowsByDate((current) => ({
        ...current,
        [openDate]: draftRowsFromStoredRows(savedDay.trades),
      }))
      setDirtyDates((current) => {
        const next = new Set(current)
        next.delete(openDate)
        return next
      })
      setIssuesByDate((current) => ({ ...current, [openDate]: [] }))
      setStatus('saved')
    } catch (requestError) {
      setStatus('error')
      setError(errorMessage(requestError, 'Day trading tracker request failed.'))
    }
  }

  function updateSelectedRows(updater: (rows: DayTradeDraftRow[]) => DayTradeDraftRow[]) {
    if (!openDate) {
      return
    }

    setDraftRowsByDate((current) => ({
      ...current,
      [openDate]: updater(current[openDate] ?? []),
    }))
    setDirtyDates((current) => new Set(current).add(openDate))
    setIssuesByDate((current) => ({ ...current, [openDate]: [] }))
    setStatus('idle')
    setError(null)
  }

  function addRow() {
    updateSelectedRows((rows) => [...rows, newDayTradeDraftRow(createLocalId('draft'))])
  }

  function updateRow(
    localId: string,
    field: DayTradeDraftField,
    value: string,
  ) {
    updateSelectedRows((rows) =>
      rows.map((row) =>
        row.localId === localId ? { ...row, [field]: value } : row,
      ),
    )
  }

  function deleteRow(localId: string) {
    updateSelectedRows((rows) => rows.filter((row) => row.localId !== localId))
  }

  return {
    today, month, setMonth, openDate, setOpenDate, draftRowsByDate, weeks,
    monthlyStats, selectedRows, selectedIssues, selectedStats, status, error,
    saveSelectedDate, addRow, updateRow, deleteRow,
  }
}
