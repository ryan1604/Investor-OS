import { useRef, useState } from 'react'

import { isAbortError } from '@/api/client'
import { errorMessage } from '@/lib/errors'

type TrackerMutationKind = 'delete' | 'notes' | 'rename' | 'strategies' | 'trades'

type TrackerMutationRequest = {
  controller: AbortController
  kind: TrackerMutationKind
  requestEpoch: number
  trackerId: string
}

export function useTrackerRequestCoordinator() {
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

export async function runTrackerMutation<Result>(
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
      setSaveError(errorMessage(error, 'Options trade tracker request failed.'))
    }
    return false
  } finally {
    requests.finishMutation(request)
  }
}
