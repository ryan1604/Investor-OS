import { useEffect, useMemo, useState } from 'react'

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
  type OptionsTradeTrackerSummary,
} from '@/api/optionsTradeTrackers'
import { isAbortError } from '@/api/client'
import { errorMessage } from '@/lib/errors'
import {
  normalizeStrategyOption,
  tradeRequestFromDraftRow,
  validateTradeDraftRows,
} from '@/features/options-trade-tracker/lib/tradeTracker'

import {
  runTrackerMutation,
  useTrackerRequestCoordinator,
} from '@/features/options-trade-tracker/hooks/useTrackerRequestCoordinator'
import {
  tradeDraftRows,
  useTradeTrackerDraftState,
} from '@/features/options-trade-tracker/hooks/useTradeTrackerDraftState'

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
          setLoadError(errorMessage(error, 'Options trade tracker request failed.'))
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
          setLoadError(errorMessage(error, 'Options trade tracker request failed.'))
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
      setSaveError(errorMessage(error, 'Options trade tracker request failed.'))
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

function sortTrackers(trackers: OptionsTradeTrackerSummary[]) {
  return [...trackers].sort((first, second) =>
    first.name.localeCompare(second.name),
  )
}
