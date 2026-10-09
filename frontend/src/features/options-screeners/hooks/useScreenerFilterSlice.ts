import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  saveOptionsScreenerFilters,
  type OptionsScreener,
  type OptionsScreenerFilterMap,
  type OptionsScreenerSettingsResponse,
} from '@/api/optionsScreeners'
import type { ScreenerFilterDraft } from '@/features/options-screeners/lib/screenerSettings'

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'invalid' | 'error'
export type SortState<Key extends string> = { key: Key; direction: 'asc' | 'desc' }

export type ScreenerFilterSlice<
  Filters,
  Key extends string,
  Draft = ScreenerFilterDraft,
> = {
  filterDraft: Draft
  filters: Filters
  filterError: string | null
  filterSaveStatus: SaveStatus
  sort: SortState<Key>
  updateFilterDraft: (field: keyof ScreenerFilterDraft, value: string) => void
  resetFilters: () => void
  setSort: (key: Key) => void
}

export function useScreenerFilterSlice<
  Screener extends OptionsScreener,
  Key extends string,
  Draft extends ScreenerFilterDraft,
>({
  screener,
  initialized,
  setSettings,
  defaultFilters,
  draftFromSettings,
  validate,
  same,
  initialSort,
}: {
  screener: Screener
  initialized: boolean
  setSettings: Dispatch<SetStateAction<OptionsScreenerSettingsResponse | null>>
  defaultFilters: OptionsScreenerFilterMap[Screener]
  draftFromSettings: (filters: OptionsScreenerFilterMap[Screener]) => Draft
  validate: (draft: Draft) => {
    filters: OptionsScreenerFilterMap[Screener] | null
    error: string | null
  }
  same: (
    first: OptionsScreenerFilterMap[Screener],
    second: OptionsScreenerFilterMap[Screener],
  ) => boolean
  initialSort: SortState<Key>
}) {
  const [filterDraft, setFilterDraft] = useState(draftFromSettings(defaultFilters))
  const [confirmedFilters, setConfirmedFilters] = useState(defaultFilters)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [sort, setSortState] = useState(initialSort)
  const validation = useMemo(() => validate(filterDraft), [filterDraft, validate])

  useFilterAutosave({
    initialized,
    screener,
    filters: validation.filters,
    confirmedFilters,
    same,
    setConfirmedFilters,
    setSaveStatus,
    setSettings,
  })

  const initialize = useCallback(
    (filters: OptionsScreenerFilterMap[Screener]) => {
      setConfirmedFilters(filters)
      setFilterDraft(draftFromSettings(filters))
      setSaveStatus('saved')
    },
    [draftFromSettings],
  )

  const updateDraft = useCallback((next: SetStateAction<Draft>) => {
    setSaveStatus('idle')
    setFilterDraft(next)
  }, [])

  const updateFilterDraft = useCallback(
    (field: keyof ScreenerFilterDraft, value: string) => {
      updateDraft((current) => ({ ...current, [field]: value }))
    },
    [updateDraft],
  )

  const resetFilters = useCallback(() => {
    updateDraft(draftFromSettings(defaultFilters))
  }, [defaultFilters, draftFromSettings, updateDraft])

  const setSort = useCallback((key: Key) => {
    setSortState((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  }, [])

  const slice = useMemo<
    ScreenerFilterSlice<OptionsScreenerFilterMap[Screener], Key, Draft>
  >(
    () => ({
      filterDraft,
      filters: confirmedFilters,
      filterError: validation.error,
      filterSaveStatus: displaySaveStatus(
        validation.error,
        validation.filters,
        confirmedFilters,
        saveStatus,
        same,
      ),
      sort,
      updateFilterDraft,
      resetFilters,
      setSort,
    }),
    [
      filterDraft,
      confirmedFilters,
      validation,
      saveStatus,
      same,
      sort,
      updateFilterDraft,
      resetFilters,
      setSort,
    ],
  )

  return { slice, initialize, updateDraft }
}

function displaySaveStatus<Filters>(
  error: string | null,
  filters: Filters | null,
  confirmedFilters: Filters,
  currentStatus: SaveStatus,
  same: (first: Filters, second: Filters) => boolean,
): SaveStatus {
  if (error) {
    return 'invalid'
  }
  if (filters && same(filters, confirmedFilters) && currentStatus !== 'saving') {
    return 'saved'
  }
  return currentStatus
}

function useFilterAutosave<Screener extends OptionsScreener>({
  initialized,
  screener,
  filters,
  confirmedFilters,
  same,
  setConfirmedFilters,
  setSaveStatus,
  setSettings,
}: {
  initialized: boolean
  screener: Screener
  filters: OptionsScreenerFilterMap[Screener] | null
  confirmedFilters: OptionsScreenerFilterMap[Screener]
  same: (
    first: OptionsScreenerFilterMap[Screener],
    second: OptionsScreenerFilterMap[Screener],
  ) => boolean
  setConfirmedFilters: (filters: OptionsScreenerFilterMap[Screener]) => void
  setSaveStatus: (status: SaveStatus) => void
  setSettings: Dispatch<SetStateAction<OptionsScreenerSettingsResponse | null>>
}) {
  const saveSequence = useRef(0)

  useEffect(() => {
    if (!initialized || !filters || same(filters, confirmedFilters)) {
      return
    }
    const nextFilters = filters
    const timeout = window.setTimeout(() => {
      const sequence = ++saveSequence.current
      setSaveStatus('saving')
      saveOptionsScreenerFilters(
        screener,
        nextFilters,
      ).then((saved) => {
        if (sequence !== saveSequence.current) {
          return
        }
        setConfirmedFilters(saved)
        setSettings((current) =>
          current
            ? {
                ...current,
                filters: { ...current.filters, [screener]: saved },
              }
            : current,
        )
        setSaveStatus('saved')
      }).catch(() => {
        if (sequence === saveSequence.current) {
          setSaveStatus('error')
        }
      })
    }, 350)
    return () => window.clearTimeout(timeout)
  }, [
    confirmedFilters,
    filters,
    initialized,
    same,
    screener,
    setConfirmedFilters,
    setSaveStatus,
    setSettings,
  ])
}
