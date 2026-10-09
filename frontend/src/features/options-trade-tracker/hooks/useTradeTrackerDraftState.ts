import { useCallback, useRef, useState } from 'react'

import type { OptionsTradeTrackerDetailResponse } from '@/api/optionsTradeTrackers'
import { createLocalId } from '@/lib/drafts'
import {
  newTradeDraftRow,
  tradeDraftRowFromStoredRow,
  type TradeDraftField,
  type TradeDraftRow,
  type TradeDraftValidationIssue,
} from '@/features/options-trade-tracker/lib/tradeTracker'

export function useTradeTrackerDraftState() {
  const [detailTrackerId, setDetailTrackerId] = useState<string | null>(null)
  const [tradeRows, setTradeRows] = useState<TradeDraftRow[]>([])
  const [notesDraft, setNotesDraft] = useState('')
  const [tradeIssues, setTradeIssues] = useState<TradeDraftValidationIssue[]>([])
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const tradeRevisionRef = useRef(0)
  const notesRevisionRef = useRef(0)

  function resetTrackerDrafts(trackerId: string | null) {
    tradeRevisionRef.current = 0
    notesRevisionRef.current = 0
    setDetailTrackerId(null)
    setTradeRows([])
    setNotesDraft('')
    setTradeIssues([])
    setIsDetailLoading(trackerId !== null)
  }

  function applyLoadedTrackerDetail(
    detail: OptionsTradeTrackerDetailResponse,
    trackerId: string,
  ) {
    if (detail.tracker.id !== trackerId) {
      return
    }

    setDetailTrackerId(trackerId)
    setTradeRows(tradeDraftRows(detail))
    setNotesDraft(detail.notes)
    setTradeIssues([])
    tradeRevisionRef.current = 0
    notesRevisionRef.current = 0
  }

  const addTradeRow = useCallback(() => {
    tradeRevisionRef.current += 1
    setTradeRows((current) => [
      ...current,
      newTradeDraftRow(createLocalId('draft')),
    ])
    setTradeIssues([])
  }, [])

  const updateTradeRow = useCallback(
    (localId: string, field: TradeDraftField, value: string) => {
      tradeRevisionRef.current += 1
      setTradeRows((current) =>
        current.map((row) =>
          row.localId === localId ? { ...row, [field]: value } : row,
        ),
      )
    },
    [],
  )

  const deleteTradeRow = useCallback((localId: string) => {
    tradeRevisionRef.current += 1
    setTradeRows((current) =>
      current.filter((row) => row.localId !== localId),
    )
    setTradeIssues((current) =>
      current.filter((issue) => issue.localId !== localId),
    )
  }, [])

  const reorderTradeRow = useCallback(
    (draggedLocalId: string, targetLocalId: string) => {
      tradeRevisionRef.current += 1
      setTradeRows((current) => {
        const draggedIndex = current.findIndex(
          (row) => row.localId === draggedLocalId,
        )
        const targetIndex = current.findIndex((row) => row.localId === targetLocalId)

        if (draggedIndex < 0 || targetIndex < 0 || draggedIndex === targetIndex) {
          return current
        }

        const next = [...current]
        const [movedRow] = next.splice(draggedIndex, 1)
        next.splice(targetIndex, 0, movedRow)
        return next
      })
    },
    [],
  )

  const updateNotesDraft = useCallback((notes: string) => {
    notesRevisionRef.current += 1
    setNotesDraft(notes)
  }, [])

  return {
    detailTrackerId,
    tradeRows,
    notesDraft,
    tradeIssues,
    isDetailLoading,
    tradeRevisionRef,
    notesRevisionRef,
    setTradeRows,
    setNotesDraft,
    setTradeIssues,
    setIsDetailLoading,
    resetTrackerDrafts,
    applyLoadedTrackerDetail,
    addTradeRow,
    updateTradeRow,
    deleteTradeRow,
    reorderTradeRow,
    updateNotesDraft,
  }
}

export function tradeDraftRows(detail: OptionsTradeTrackerDetailResponse) {
  return [...detail.trades]
    .sort((first, second) => first.display_order - second.display_order)
    .map(tradeDraftRowFromStoredRow)
}
