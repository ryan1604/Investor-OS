import { useEffect, useMemo, useRef, useState } from 'react'

import {
  createOptionsTradeTracker,
  deleteOptionsTradeTracker,
  fetchOptionsTradeStrategyOptions,
  fetchOptionsTradeTracker,
  fetchOptionsTradeTrackers,
  renameOptionsTradeTracker,
  replaceOptionsTradeStrategyOptions,
  replaceOptionsTradeTrackerTrades,
  updateOptionsTradeTrackerNotes,
  type OptionsTradeTrackerDetailResponse,
  type OptionsTradeTrackerSummary,
} from '@/api/optionsTradeTrackers'
import { isAbortError } from '@/api/client'
import {
  newTradeDraftRow,
  normalizeStrategyOption,
  tradeDraftRowFromStoredRow,
  tradeRequestFromDraftRow,
  validateTradeDraftRows,
  type TradeDraftField,
  type TradeDraftRow,
  type TradeDraftValidationIssue,
} from '@/features/options-trade-tracker/lib/tradeTracker'

type TrackerMutationKind = 'delete' | 'notes' | 'rename' | 'strategies' | 'trades'

type TrackerMutationRequest = {
  controller: AbortController
  kind: TrackerMutationKind
  requestEpoch: number
  trackerId: string
}

export function useOptionsTradeTracker() {
  const [trackers, setTrackers] = useState<OptionsTradeTrackerSummary[]>([])
  const [strategyOptions, setStrategyOptions] = useState<string[]>([])
  const [selectedTrackerId, setSelectedTrackerId] = useState<string | null>(null)
  const [detailTrackerId, setDetailTrackerId] = useState<string | null>(null)
  const [tradeRows, setTradeRows] = useState<TradeDraftRow[]>([])
  const [notesDraft, setNotesDraft] = useState('')
  const [tradeIssues, setTradeIssues] = useState<TradeDraftValidationIssue[]>([])
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savingKinds, setSavingKinds] = useState<Set<TrackerMutationKind>>(
    () => new Set(),
  )
  const selectedTrackerIdRef = useRef<string | null>(null)
  const trackerRequestEpochRef = useRef(0)
  const tradeRevisionRef = useRef(0)
  const notesRevisionRef = useRef(0)
  const detailControllerRef = useRef<AbortController | null>(null)
  const mutationControllersRef = useRef(
    new Map<TrackerMutationKind, AbortController>(),
  )

  const selectedTracker = useMemo(
    () => trackers.find((tracker) => tracker.id === selectedTrackerId) ?? null,
    [selectedTrackerId, trackers],
  )

  useEffect(() => {
    const controller = new AbortController()

    async function loadTrackerShell() {
      setIsInitialLoading(true)
      setLoadError(null)

      try {
        const [trackerList, strategies] = await Promise.all([
          fetchOptionsTradeTrackers(controller.signal),
          fetchOptionsTradeStrategyOptions(controller.signal),
        ])

        if (controller.signal.aborted) {
          return
        }

        setTrackers(trackerList.trackers)
        setStrategyOptions(strategies.strategies)
        const initialTrackerId = trackerList.trackers[0]?.id ?? null
        trackerRequestEpochRef.current += 1
        selectedTrackerIdRef.current = initialTrackerId
        setSelectedTrackerId(initialTrackerId)
        resetTrackerDrafts(initialTrackerId)
      } catch (error) {
        if (!isAbortError(error)) {
          setLoadError(errorMessage(error))
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsInitialLoading(false)
        }
      }
    }

    void loadTrackerShell()

    return () => {
      controller.abort()
      invalidateTrackerRequests()
    }
  }, [])

  useEffect(() => {
    if (selectedTrackerId === null) {
      return
    }

    const trackerId = selectedTrackerId
    const requestEpoch = trackerRequestEpochRef.current
    const controller = new AbortController()
    detailControllerRef.current?.abort()
    detailControllerRef.current = controller

    async function loadTrackerDetail() {
      setIsDetailLoading(true)
      setLoadError(null)

      try {
        const detail = await fetchOptionsTradeTracker(trackerId, controller.signal)

        if (isCurrentTrackerRequest(trackerId, requestEpoch)) {
          applyLoadedTrackerDetail(detail, trackerId)
        }
      } catch (error) {
        if (!isAbortError(error) && isCurrentTrackerRequest(trackerId, requestEpoch)) {
          setLoadError(errorMessage(error))
        }
      } finally {
        if (isCurrentTrackerRequest(trackerId, requestEpoch)) {
          setIsDetailLoading(false)
        }
        if (detailControllerRef.current === controller) {
          detailControllerRef.current = null
        }
      }
    }

    void loadTrackerDetail()

    return () => {
      controller.abort()
    }
  }, [selectedTrackerId])

  function invalidateTrackerRequests() {
    trackerRequestEpochRef.current += 1
    detailControllerRef.current?.abort()
    detailControllerRef.current = null
    mutationControllersRef.current.forEach((controller) => controller.abort())
    mutationControllersRef.current.clear()
  }

  function resetTrackerDrafts(trackerId: string | null) {
    tradeRevisionRef.current = 0
    notesRevisionRef.current = 0
    setDetailTrackerId(null)
    setTradeRows([])
    setNotesDraft('')
    setTradeIssues([])
    setIsDetailLoading(trackerId !== null)
  }

  function selectTracker(trackerId: string | null) {
    if (selectedTrackerIdRef.current === trackerId) {
      return
    }

    invalidateTrackerRequests()
    selectedTrackerIdRef.current = trackerId
    setSelectedTrackerId(trackerId)
    resetTrackerDrafts(trackerId)
    setLoadError(null)
    setSaveError(null)
    setSavingKinds(new Set())
  }

  function isCurrentTrackerRequest(trackerId: string, requestEpoch: number) {
    return (
      selectedTrackerIdRef.current === trackerId &&
      trackerRequestEpochRef.current === requestEpoch
    )
  }

  function beginTrackerMutation(
    kind: TrackerMutationKind,
    trackerId: string,
  ): TrackerMutationRequest {
    mutationControllersRef.current.get(kind)?.abort()
    const controller = new AbortController()
    mutationControllersRef.current.set(kind, controller)
    setSavingKinds((current) => new Set(current).add(kind))
    return {
      controller,
      kind,
      requestEpoch: trackerRequestEpochRef.current,
      trackerId,
    }
  }

  function isCurrentMutation(request: TrackerMutationRequest) {
    return (
      isCurrentTrackerRequest(request.trackerId, request.requestEpoch) &&
      mutationControllersRef.current.get(request.kind) === request.controller
    )
  }

  function finishMutation(request: TrackerMutationRequest) {
    if (!isCurrentMutation(request)) {
      return
    }

    mutationControllersRef.current.delete(request.kind)
    setSavingKinds((current) => {
      const next = new Set(current)
      next.delete(request.kind)
      return next
    })
  }

  function applyLoadedTrackerDetail(
    detail: OptionsTradeTrackerDetailResponse,
    trackerId: string,
  ) {
    if (
      selectedTrackerIdRef.current !== trackerId ||
      detail.tracker.id !== trackerId
    ) {
      return
    }

    setDetailTrackerId(trackerId)
    setTradeRows(tradeDraftRows(detail))
    setNotesDraft(detail.notes)
    setTradeIssues([])
    tradeRevisionRef.current = 0
    notesRevisionRef.current = 0
  }

  async function createTracker(name: string) {
    setIsCreating(true)
    setSaveError(null)

    try {
      const detail = await createOptionsTradeTracker({ name })
      setTrackers((current) => sortTrackers([...current, detail.tracker]))
      selectTracker(detail.tracker.id)
      applyLoadedTrackerDetail(detail, detail.tracker.id)
      setIsDetailLoading(false)
      return true
    } catch (error) {
      setSaveError(errorMessage(error))
      return false
    } finally {
      setIsCreating(false)
    }
  }

  async function renameSelectedTracker(name: string) {
    if (selectedTrackerId === null) {
      return false
    }

    const request = beginTrackerMutation('rename', selectedTrackerId)
    setSaveError(null)

    try {
      const detail = await renameOptionsTradeTracker(
        selectedTrackerId,
        { name },
        request.controller.signal,
      )
      if (!isCurrentMutation(request) || detail.tracker.id !== request.trackerId) {
        return false
      }
      setTrackers((current) =>
        sortTrackers(
          current.map((tracker) =>
            tracker.id === detail.tracker.id ? detail.tracker : tracker,
          ),
        ),
      )
      return true
    } catch (error) {
      if (!isAbortError(error) && isCurrentMutation(request)) {
        setSaveError(errorMessage(error))
      }
      return false
    } finally {
      finishMutation(request)
    }
  }

  async function deleteSelectedTracker() {
    if (selectedTrackerId === null) {
      return false
    }

    const trackerId = selectedTrackerId
    const request = beginTrackerMutation('delete', trackerId)
    setSaveError(null)

    try {
      await deleteOptionsTradeTracker(trackerId, request.controller.signal)
      if (!isCurrentMutation(request)) {
        return false
      }
      setTrackers((current) =>
        current.filter((tracker) => tracker.id !== trackerId),
      )
      selectTracker(null)
      return true
    } catch (error) {
      if (!isAbortError(error) && isCurrentMutation(request)) {
        setSaveError(errorMessage(error))
      }
      return false
    } finally {
      finishMutation(request)
    }
  }

  function addTradeRow() {
    tradeRevisionRef.current += 1
    setTradeRows((current) => [
      ...current,
      newTradeDraftRow(createLocalTradeId()),
    ])
    setTradeIssues([])
  }

  function updateTradeRow(
    localId: string,
    field: TradeDraftField,
    value: string,
  ) {
    tradeRevisionRef.current += 1
    setTradeRows((current) =>
      current.map((row) =>
        row.localId === localId ? { ...row, [field]: value } : row,
      ),
    )
  }

  function deleteTradeRow(localId: string) {
    tradeRevisionRef.current += 1
    setTradeRows((current) =>
      current.filter((row) => row.localId !== localId),
    )
    setTradeIssues((current) =>
      current.filter((issue) => issue.localId !== localId),
    )
  }

  function reorderTradeRow(draggedLocalId: string, targetLocalId: string) {
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
  }

  async function saveTradeRows() {
    if (selectedTrackerId === null) {
      return
    }

    const issues = validateTradeDraftRows(tradeRows)
    setTradeIssues(issues)
    if (issues.length > 0) {
      setSaveError('Resolve trade row validation before saving.')
      return
    }

    const trackerId = selectedTrackerId
    const savedRevision = tradeRevisionRef.current
    const request = beginTrackerMutation('trades', trackerId)
    setSaveError(null)

    try {
      const detail = await replaceOptionsTradeTrackerTrades(
        trackerId,
        {
          trades: tradeRows.map((row, index) =>
            tradeRequestFromDraftRow(row, index + 1),
          ),
        },
        request.controller.signal,
      )
      if (
        isCurrentMutation(request) &&
        detail.tracker.id === trackerId &&
        tradeRevisionRef.current === savedRevision
      ) {
        setTradeRows(tradeDraftRows(detail))
        setTradeIssues([])
      }
    } catch (error) {
      if (!isAbortError(error) && isCurrentMutation(request)) {
        setSaveError(errorMessage(error))
      }
    } finally {
      finishMutation(request)
    }
  }

  function updateNotesDraft(notes: string) {
    notesRevisionRef.current += 1
    setNotesDraft(notes)
  }

  async function saveNotes() {
    if (selectedTrackerId === null) {
      return
    }

    const trackerId = selectedTrackerId
    const savedRevision = notesRevisionRef.current
    const request = beginTrackerMutation('notes', trackerId)
    setSaveError(null)

    try {
      const detail = await updateOptionsTradeTrackerNotes(
        trackerId,
        { notes: notesDraft },
        request.controller.signal,
      )
      if (
        isCurrentMutation(request) &&
        detail.tracker.id === trackerId &&
        notesRevisionRef.current === savedRevision
      ) {
        setNotesDraft(detail.notes)
      }
    } catch (error) {
      if (!isAbortError(error) && isCurrentMutation(request)) {
        setSaveError(errorMessage(error))
      }
    } finally {
      finishMutation(request)
    }
  }

  async function createStrategyOption(strategy: string) {
    if (selectedTrackerId === null) {
      return false
    }

    const normalizedStrategy = normalizeStrategyOption(strategy)
    if (!normalizedStrategy) {
      setSaveError('Strategy name is required.')
      return false
    }

    const nextStrategies = [
      ...strategyOptions.map(normalizeStrategyOption),
      normalizedStrategy,
    ].filter(
      (value, index, values) =>
        values.findIndex(
          (candidate) => candidate.toLowerCase() === value.toLowerCase(),
        ) === index,
    )
    const request = beginTrackerMutation('strategies', selectedTrackerId)
    setSaveError(null)

    try {
      const response = await replaceOptionsTradeStrategyOptions(
        { strategies: nextStrategies },
        request.controller.signal,
      )
      if (!isCurrentMutation(request)) {
        return false
      }
      setStrategyOptions(response.strategies)
      return true
    } catch (error) {
      if (!isAbortError(error) && isCurrentMutation(request)) {
        setSaveError(errorMessage(error))
      }
      return false
    } finally {
      finishMutation(request)
    }
  }

  return {
    trackers,
    strategyOptions,
    selectedTracker,
    selectedTrackerId,
    detailTrackerId,
    tradeRows,
    notesDraft,
    tradeIssues,
    isInitialLoading,
    isDetailLoading,
    isCreating,
    loadError,
    saveError,
    isDeleting: savingKinds.has('delete'),
    isSavingMetadata: savingKinds.has('rename'),
    isSavingNotes: savingKinds.has('notes'),
    isSavingStrategies: savingKinds.has('strategies'),
    isSavingTrades: savingKinds.has('trades'),
    setSaveError,
    selectTracker,
    createTracker,
    renameSelectedTracker,
    deleteSelectedTracker,
    addTradeRow,
    updateTradeRow,
    deleteTradeRow,
    reorderTradeRow,
    saveTradeRows,
    updateNotesDraft,
    saveNotes,
    createStrategyOption,
  }
}

function tradeDraftRows(detail: OptionsTradeTrackerDetailResponse) {
  return [...detail.trades]
    .sort((first, second) => first.display_order - second.display_order)
    .map(tradeDraftRowFromStoredRow)
}

function sortTrackers(trackers: OptionsTradeTrackerSummary[]) {
  return [...trackers].sort((first, second) =>
    first.name.localeCompare(second.name),
  )
}

function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : 'Options trade tracker request failed.'
}

function createLocalTradeId() {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
