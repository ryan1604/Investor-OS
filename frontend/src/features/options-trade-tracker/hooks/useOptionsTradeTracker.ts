import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
import { errorMessage as requestErrorMessage, isAbortError } from '@/api/client'
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
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const requests = useTrackerRequestCoordinator()
  const drafts = useTradeTrackerDraftState()

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
        requests.startTrackerRequest(initialTrackerId)
        setSelectedTrackerId(initialTrackerId)
        drafts.resetTrackerDrafts(initialTrackerId)
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
      requests.invalidateTrackerRequests()
    }
    // Request refs and draft setters intentionally own this mount lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (selectedTrackerId === null) {
      return
    }

    const trackerId = selectedTrackerId
    const requestEpoch = requests.trackerRequestEpochRef.current
    const controller = new AbortController()
    requests.replaceDetailController(controller)

    async function loadTrackerDetail() {
      drafts.setIsDetailLoading(true)
      setLoadError(null)

      try {
        const detail = await fetchOptionsTradeTracker(trackerId, controller.signal)

        if (requests.isCurrentTrackerRequest(trackerId, requestEpoch)) {
          drafts.applyLoadedTrackerDetail(detail, trackerId)
        }
      } catch (error) {
        if (
          !isAbortError(error) &&
          requests.isCurrentTrackerRequest(trackerId, requestEpoch)
        ) {
          setLoadError(errorMessage(error))
        }
      } finally {
        if (requests.isCurrentTrackerRequest(trackerId, requestEpoch)) {
          drafts.setIsDetailLoading(false)
        }
        requests.clearDetailController(controller)
      }
    }

    void loadTrackerDetail()

    return () => {
      controller.abort()
    }
    // Request refs and draft setters intentionally own selected-tracker changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTrackerId])

  function selectTracker(trackerId: string | null) {
    if (requests.selectedTrackerIdRef.current === trackerId) {
      return
    }

    requests.invalidateTrackerRequests()
    requests.setSelectedTrackerIdRef(trackerId)
    setSelectedTrackerId(trackerId)
    drafts.resetTrackerDrafts(trackerId)
    setLoadError(null)
    setSaveError(null)
    requests.clearSavingKinds()
  }

  async function createTracker(name: string) {
    setIsCreating(true)
    setSaveError(null)

    try {
      const detail = await createOptionsTradeTracker({ name })
      setTrackers((current) => sortTrackers([...current, detail.tracker]))
      selectTracker(detail.tracker.id)
      drafts.applyLoadedTrackerDetail(detail, detail.tracker.id)
      drafts.setIsDetailLoading(false)
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

    const request = requests.beginTrackerMutation('rename', selectedTrackerId)
    return runTrackerMutation(
      requests,
      request,
      setSaveError,
      (signal) => renameOptionsTradeTracker(selectedTrackerId, { name }, signal),
      (detail) => {
        if (detail.tracker.id !== request.trackerId) {
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
      },
    )
  }

  async function deleteSelectedTracker() {
    if (selectedTrackerId === null) {
      return false
    }

    const trackerId = selectedTrackerId
    const request = requests.beginTrackerMutation('delete', trackerId)
    return runTrackerMutation(
      requests,
      request,
      setSaveError,
      (signal) => deleteOptionsTradeTracker(trackerId, signal),
      () => {
        setTrackers((current) =>
          current.filter((tracker) => tracker.id !== trackerId),
        )
        selectTracker(null)
        return true
      },
    )
  }

  async function saveTradeRows() {
    if (selectedTrackerId === null) {
      return
    }

    const issues = validateTradeDraftRows(drafts.tradeRows)
    drafts.setTradeIssues(issues)
    if (issues.length > 0) {
      setSaveError('Resolve trade row validation before saving.')
      return
    }

    const trackerId = selectedTrackerId
    const savedRevision = drafts.tradeRevisionRef.current
    const request = requests.beginTrackerMutation('trades', trackerId)
    await runTrackerMutation(
      requests,
      request,
      setSaveError,
      (signal) =>
        replaceOptionsTradeTrackerTrades(
          trackerId,
          {
            trades: drafts.tradeRows.map((row, index) =>
              tradeRequestFromDraftRow(row, index + 1),
            ),
          },
          signal,
        ),
      (detail) => {
        if (
          detail.tracker.id === trackerId &&
          drafts.tradeRevisionRef.current === savedRevision
        ) {
          drafts.setTradeRows(tradeDraftRows(detail))
          drafts.setTradeIssues([])
        }
        return true
      },
    )
  }

  async function saveNotes() {
    if (selectedTrackerId === null) {
      return
    }

    const trackerId = selectedTrackerId
    const savedRevision = drafts.notesRevisionRef.current
    const request = requests.beginTrackerMutation('notes', trackerId)
    await runTrackerMutation(
      requests,
      request,
      setSaveError,
      (signal) =>
        updateOptionsTradeTrackerNotes(
          trackerId,
          { notes: drafts.notesDraft },
          signal,
        ),
      (detail) => {
        if (
          detail.tracker.id === trackerId &&
          drafts.notesRevisionRef.current === savedRevision
        ) {
          drafts.setNotesDraft(detail.notes)
        }
        return true
      },
    )
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
    const request = requests.beginTrackerMutation('strategies', selectedTrackerId)
    return runTrackerMutation(
      requests,
      request,
      setSaveError,
      (signal) =>
        replaceOptionsTradeStrategyOptions({ strategies: nextStrategies }, signal),
      (response) => {
        setStrategyOptions(response.strategies)
        return true
      },
    )
  }

  return {
    trackers,
    strategyOptions,
    selectedTracker,
    selectedTrackerId,
    detailTrackerId: drafts.detailTrackerId,
    tradeRows: drafts.tradeRows,
    notesDraft: drafts.notesDraft,
    tradeIssues: drafts.tradeIssues,
    isInitialLoading,
    isDetailLoading: drafts.isDetailLoading,
    isCreating,
    loadError,
    saveError,
    isDeleting: requests.savingKinds.has('delete'),
    isSavingMetadata: requests.savingKinds.has('rename'),
    isSavingNotes: requests.savingKinds.has('notes'),
    isSavingStrategies: requests.savingKinds.has('strategies'),
    isSavingTrades: requests.savingKinds.has('trades'),
    setSaveError,
    selectTracker,
    createTracker,
    renameSelectedTracker,
    deleteSelectedTracker,
    addTradeRow: drafts.addTradeRow,
    updateTradeRow: drafts.updateTradeRow,
    deleteTradeRow: drafts.deleteTradeRow,
    reorderTradeRow: drafts.reorderTradeRow,
    saveTradeRows,
    updateNotesDraft: drafts.updateNotesDraft,
    saveNotes,
    createStrategyOption,
  }
}

function useTrackerRequestCoordinator() {
  const [savingKinds, setSavingKinds] = useState<Set<TrackerMutationKind>>(
    () => new Set(),
  )
  const selectedTrackerIdRef = useRef<string | null>(null)
  const trackerRequestEpochRef = useRef(0)
  const detailControllerRef = useRef<AbortController | null>(null)
  const mutationControllersRef = useRef(
    new Map<TrackerMutationKind, AbortController>(),
  )

  function startTrackerRequest(trackerId: string | null) {
    trackerRequestEpochRef.current += 1
    selectedTrackerIdRef.current = trackerId
  }

  function setSelectedTrackerIdRef(trackerId: string | null) {
    selectedTrackerIdRef.current = trackerId
  }

  function invalidateTrackerRequests() {
    trackerRequestEpochRef.current += 1
    detailControllerRef.current?.abort()
    detailControllerRef.current = null
    mutationControllersRef.current.forEach((controller) => controller.abort())
    mutationControllersRef.current.clear()
  }

  function replaceDetailController(controller: AbortController) {
    detailControllerRef.current?.abort()
    detailControllerRef.current = controller
  }

  function clearDetailController(controller: AbortController) {
    if (detailControllerRef.current === controller) {
      detailControllerRef.current = null
    }
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

  function clearSavingKinds() {
    setSavingKinds(new Set())
  }

  return {
    savingKinds,
    selectedTrackerIdRef,
    trackerRequestEpochRef,
    startTrackerRequest,
    setSelectedTrackerIdRef,
    invalidateTrackerRequests,
    replaceDetailController,
    clearDetailController,
    isCurrentTrackerRequest,
    beginTrackerMutation,
    isCurrentMutation,
    finishMutation,
    clearSavingKinds,
  }
}

async function runTrackerMutation<Result>(
  requests: ReturnType<typeof useTrackerRequestCoordinator>,
  request: TrackerMutationRequest,
  setSaveError: (error: string | null) => void,
  action: (signal: AbortSignal) => Promise<Result>,
  apply: (result: Result) => boolean,
) {
  setSaveError(null)

  try {
    const result = await action(request.controller.signal)
    if (!requests.isCurrentMutation(request)) {
      return false
    }
    return apply(result)
  } catch (error) {
    if (!isAbortError(error) && requests.isCurrentMutation(request)) {
      setSaveError(errorMessage(error))
    }
    return false
  } finally {
    requests.finishMutation(request)
  }
}

function useTradeTrackerDraftState() {
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
      newTradeDraftRow(createLocalTradeId()),
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
  return requestErrorMessage(error, 'Options trade tracker request failed.')
}

function createLocalTradeId() {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
