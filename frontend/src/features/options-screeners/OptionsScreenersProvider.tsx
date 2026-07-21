/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  cancelOptionsScreenerScan,
  fetchOptionsScreenerScanState,
  fetchOptionsScreenerSettings,
  getOptionsScreenerScansWsUrl,
  replaceOptionsScreenerTickerList,
  saveOptionsScreenerFilters,
  startOptionsScreenerScan,
  type CreditSpreadScreenerFilters,
  type CreditSpreadStrategy,
  type CreditSpreadWidth,
  type OptionsScreenerTickerList,
  type OptionsScreenerCompletedSnapshot,
  type OptionsScreenerFilters,
  type OptionsScreenerScanEvent,
  type OptionsScreenerScanJob,
  type OptionsScreenerScanState,
  type OptionsScreenerSettingsResponse,
} from '@/api/optionsScreeners'
import { errorMessage as requestErrorMessage } from '@/api/client'
import type {
  CashSecuredPutCandidate,
  CoveredCallCandidate,
  CreditSpreadCandidate,
} from '@/features/options-screeners/lib/screenerResults'
import type { SingleLegSortKey } from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  defaultCspFilters,
  defaultCsFilters,
  creditSpreadFilterDraftFromSettings,
  type CreditSpreadFilterDraft,
  filterDraftFromSettings,
  type ScreenerFilterDraft,
  validateCreditSpreadFilterDraft,
  validateFilterDraft,
} from '@/features/options-screeners/lib/screenerSettings'

export type CspSortKey = Exclude<SingleLegSortKey, 'gain_percentage'>
export type CcSortKey = Exclude<SingleLegSortKey, 'discount_percentage'>
export type CsSortKey =
  | 'ticker'
  | 'strategy'
  | 'annualized_return'
  | 'stock_price'
  | 'short_strike'
  | 'long_strike'
  | 'expiration'
  | 'dte'
  | 'short_delta'
  | 'net_bid'
  | 'net_ask'
  | 'distance_percentage'

type SaveStatus = 'idle' | 'saving' | 'saved' | 'invalid' | 'error'
type SortDirection = 'asc' | 'desc'
type SortState<Key extends string> = { key: Key; direction: SortDirection }

type OptionsScreenersContextValue = {
  isLoading: boolean
  loadError: string | null
  cspTickers: string[]
  csTickers: string[]
  cspFilterDraft: ScreenerFilterDraft
  cspFilters: OptionsScreenerFilters
  cspFilterError: string | null
  cspFilterSaveStatus: SaveStatus
  ccFilterDraft: ScreenerFilterDraft
  ccFilters: OptionsScreenerFilters
  ccFilterError: string | null
  ccFilterSaveStatus: SaveStatus
  csFilterDraft: CreditSpreadFilterDraft
  csFilters: CreditSpreadScreenerFilters
  csFilterError: string | null
  csFilterSaveStatus: SaveStatus
  tickerSaveError: string | null
  isTickerUpdatePending: boolean
  scanActionError: string | null
  activeJob: OptionsScreenerScanJob | null
  latestCspJob: OptionsScreenerScanJob | null
  latestCcJob: OptionsScreenerScanJob | null
  latestCsJob: OptionsScreenerScanJob | null
  cspSnapshot: OptionsScreenerCompletedSnapshot | null
  ccSnapshot: OptionsScreenerCompletedSnapshot | null
  csSnapshot: OptionsScreenerCompletedSnapshot | null
  cspSort: { key: CspSortKey; direction: 'asc' | 'desc' }
  ccSort: { key: CcSortKey; direction: 'asc' | 'desc' }
  csSort: { key: CsSortKey; direction: 'asc' | 'desc' }
  addCspTickers: (tickers: string[]) => Promise<void>
  removeCspTicker: (ticker: string) => Promise<void>
  clearCspTickers: () => Promise<void>
  addCsTickers: (tickers: string[]) => Promise<void>
  removeCsTicker: (ticker: string) => Promise<void>
  clearCsTickers: () => Promise<void>
  updateCspFilterDraft: (
    field: keyof ScreenerFilterDraft,
    value: string,
  ) => void
  resetCspFilters: () => void
  updateCcFilterDraft: (
    field: keyof ScreenerFilterDraft,
    value: string,
  ) => void
  resetCcFilters: () => void
  updateCsFilterDraft: (
    field: keyof ScreenerFilterDraft,
    value: string,
  ) => void
  toggleCsStrategyType: (strategy: CreditSpreadStrategy) => void
  toggleCsSpreadWidth: (width: CreditSpreadWidth) => void
  resetCsFilters: () => void
  startCspScan: () => Promise<void>
  startCcScan: () => Promise<void>
  startCsScan: () => Promise<void>
  cancelActiveScan: () => Promise<void>
  setCspSort: (key: CspSortKey) => void
  setCcSort: (key: CcSortKey) => void
  setCsSort: (key: CsSortKey) => void
}

const OptionsScreenersContext =
  createContext<OptionsScreenersContextValue | null>(null)

const emptyScanState: OptionsScreenerScanState = {
  active_job: null,
  latest_jobs: { csp: null, cc: null, cs: null },
  completed_snapshots: { csp: null, cc: null, cs: null },
}

export function OptionsScreenersProvider({
  children,
}: {
  children: ReactNode
}) {
  const [settings, setSettings] =
    useState<OptionsScreenerSettingsResponse | null>(null)
  const [scanState, setScanState] =
    useState<OptionsScreenerScanState>(emptyScanState)
  const [cspFilterDraft, setCspFilterDraft] = useState(
    filterDraftFromSettings(defaultCspFilters),
  )
  const [ccFilterDraft, setCcFilterDraft] = useState(
    filterDraftFromSettings(defaultCspFilters),
  )
  const [csFilterDraft, setCsFilterDraft] = useState(
    creditSpreadFilterDraftFromSettings(defaultCsFilters),
  )
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tickerSaveError, setTickerSaveError] = useState<string | null>(null)
  const [isTickerUpdatePending, setIsTickerUpdatePending] = useState(false)
  const [cspFilterSaveStatus, setCspFilterSaveStatus] =
    useState<SaveStatus>('idle')
  const [confirmedCspFilters, setConfirmedCspFilters] =
    useState(defaultCspFilters)
  const [ccFilterSaveStatus, setCcFilterSaveStatus] =
    useState<SaveStatus>('idle')
  const [confirmedCcFilters, setConfirmedCcFilters] =
    useState(defaultCspFilters)
  const [csFilterSaveStatus, setCsFilterSaveStatus] =
    useState<SaveStatus>('idle')
  const [confirmedCsFilters, setConfirmedCsFilters] =
    useState(defaultCsFilters)
  const [scanActionError, setScanActionError] = useState<string | null>(null)
  const [sorts, setSorts] = useState({
    csp: { key: 'annualized_return', direction: 'desc' } as SortState<CspSortKey>,
    cc: { key: 'annualized_return', direction: 'desc' } as SortState<CcSortKey>,
    cs: { key: 'annualized_return', direction: 'desc' } as SortState<CsSortKey>,
  })
  const confirmedTickersRef = useRef<Record<OptionsScreenerTickerList, string[]>>({
    csp_cc: [],
    cs: [],
  })
  const [filtersInitialized, setFiltersInitialized] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      fetchOptionsScreenerSettings(controller.signal),
      fetchOptionsScreenerScanState(controller.signal),
    ])
      .then(([nextSettings, nextScanState]) => {
        setSettings(nextSettings)
        setScanState(nextScanState)
        confirmedTickersRef.current = {
          csp_cc: nextSettings.ticker_lists.csp_cc,
          cs: nextSettings.ticker_lists.cs,
        }
        setConfirmedCspFilters(nextSettings.filters.csp)
        setCspFilterDraft(filterDraftFromSettings(nextSettings.filters.csp))
        setCspFilterSaveStatus('saved')
        setConfirmedCcFilters(nextSettings.filters.cc)
        setCcFilterDraft(filterDraftFromSettings(nextSettings.filters.cc))
        setCcFilterSaveStatus('saved')
        setConfirmedCsFilters(nextSettings.filters.cs)
        setCsFilterDraft(creditSpreadFilterDraftFromSettings(nextSettings.filters.cs))
        setCsFilterSaveStatus('saved')
        setFiltersInitialized(true)
        setLoadError(null)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(errorMessage(error))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (isLoading) {
      return
    }
    if (typeof WebSocket === 'undefined') {
      return
    }
    const socket = new WebSocket(getOptionsScreenerScansWsUrl())
    socket.onmessage = (event) => {
      const update = JSON.parse(event.data) as OptionsScreenerScanEvent
      setScanState((current) => applyScanEvent(current, update))
    }
    return () => socket.close()
  }, [isLoading])

  const validation = useMemo(
    () => validateFilterDraft(cspFilterDraft),
    [cspFilterDraft],
  )
  const ccValidation = useMemo(
    () => validateFilterDraft(ccFilterDraft),
    [ccFilterDraft],
  )
  const csValidation = useMemo(
    () => validateCreditSpreadFilterDraft(csFilterDraft),
    [csFilterDraft],
  )

  useFilterAutosave({
    initialized: filtersInitialized,
    screener: 'csp',
    filters: validation.filters,
    confirmedFilters: confirmedCspFilters,
    same: sameFilters,
    setConfirmedFilters: setConfirmedCspFilters,
    setSaveStatus: setCspFilterSaveStatus,
    setSettings,
  })
  useFilterAutosave({
    initialized: filtersInitialized,
    screener: 'cc',
    filters: ccValidation.filters,
    confirmedFilters: confirmedCcFilters,
    same: sameFilters,
    setConfirmedFilters: setConfirmedCcFilters,
    setSaveStatus: setCcFilterSaveStatus,
    setSettings,
  })
  useFilterAutosave({
    initialized: filtersInitialized,
    screener: 'cs',
    filters: csValidation.filters,
    confirmedFilters: confirmedCsFilters,
    same: sameCreditSpreadFilters,
    setConfirmedFilters: setConfirmedCsFilters,
    setSaveStatus: setCsFilterSaveStatus,
    setSettings,
  })

  const saveTickers = useCallback(async (
    listName: OptionsScreenerTickerList,
    nextTickers: string[],
  ) => {
    if (isTickerUpdatePending) {
      return
    }
    const previous = confirmedTickersRef.current[listName]
    setTickerSaveError(null)
    setIsTickerUpdatePending(true)
    setSettings((current) =>
      current
        ? {
            ...current,
            ticker_lists: { ...current.ticker_lists, [listName]: nextTickers },
          }
        : current,
    )
    try {
      const response = await replaceOptionsScreenerTickerList(
        listName,
        nextTickers,
      )
      confirmedTickersRef.current = {
        ...confirmedTickersRef.current,
        [listName]: response.tickers,
      }
      setSettings((current) =>
        current
          ? {
              ...current,
              ticker_lists: {
                ...current.ticker_lists,
                [listName]: response.tickers,
              },
            }
          : current,
      )
    } catch (error) {
      setSettings((current) =>
        current
          ? {
              ...current,
              ticker_lists: { ...current.ticker_lists, [listName]: previous },
            }
          : current,
      )
      setTickerSaveError(errorMessage(error))
    } finally {
      setIsTickerUpdatePending(false)
    }
  }, [isTickerUpdatePending])

  const addCspTickers = useCallback(
    (tickers: string[]) =>
      addTickersToList('csp_cc', tickers, settings, saveTickers),
    [saveTickers, settings],
  )

  const addCsTickers = useCallback(
    (tickers: string[]) =>
      addTickersToList('cs', tickers, settings, saveTickers),
    [saveTickers, settings],
  )

  const startScan = useCallback(async (screener: 'csp' | 'cc' | 'cs') => {
    setScanActionError(null)
    try {
      const job = await startOptionsScreenerScan(screener)
      setScanState((current) => ({
        ...current,
        active_job: job,
        latest_jobs: { ...current.latest_jobs, [screener]: job },
      }))
    } catch (error) {
      setScanActionError(errorMessage(error))
    }
  }, [])
  const startCspScan = useCallback(() => startScan('csp'), [startScan])
  const startCcScan = useCallback(() => startScan('cc'), [startScan])
  const startCsScan = useCallback(() => startScan('cs'), [startScan])

  const cancelActiveScan = useCallback(async () => {
    if (!scanState.active_job) {
      return
    }
    setScanActionError(null)
    try {
      await cancelOptionsScreenerScan(scanState.active_job.id)
    } catch (error) {
      setScanActionError(errorMessage(error))
    }
  }, [scanState.active_job])

  const value = useMemo<OptionsScreenersContextValue>(
    () => ({
      isLoading,
      loadError,
      cspTickers: settings?.ticker_lists.csp_cc ?? [],
      csTickers: settings?.ticker_lists.cs ?? [],
      cspFilterDraft,
      cspFilters: confirmedCspFilters,
      cspFilterError: validation.error,
      cspFilterSaveStatus: displaySaveStatus(
        validation.error,
        validation.filters,
        confirmedCspFilters,
        cspFilterSaveStatus,
        sameFilters,
      ),
      ccFilterDraft,
      ccFilters: confirmedCcFilters,
      ccFilterError: ccValidation.error,
      ccFilterSaveStatus: displaySaveStatus(
        ccValidation.error,
        ccValidation.filters,
        confirmedCcFilters,
        ccFilterSaveStatus,
        sameFilters,
      ),
      csFilterDraft,
      csFilters: confirmedCsFilters,
      csFilterError: csValidation.error,
      csFilterSaveStatus: displaySaveStatus(
        csValidation.error,
        csValidation.filters,
        confirmedCsFilters,
        csFilterSaveStatus,
        sameCreditSpreadFilters,
      ),
      tickerSaveError,
      isTickerUpdatePending,
      scanActionError,
      activeJob: scanState.active_job,
      latestCspJob: scanState.latest_jobs.csp,
      latestCcJob: scanState.latest_jobs.cc,
      latestCsJob: scanState.latest_jobs.cs,
      cspSnapshot: scanState.completed_snapshots.csp,
      ccSnapshot: scanState.completed_snapshots.cc,
      csSnapshot: scanState.completed_snapshots.cs,
      cspSort: sorts.csp,
      ccSort: sorts.cc,
      csSort: sorts.cs,
      addCspTickers,
      addCsTickers,
      removeCspTicker: (ticker) =>
        saveTickers(
          'csp_cc',
          (settings?.ticker_lists.csp_cc ?? []).filter(
            (item) => item !== ticker,
          ),
        ),
      clearCspTickers: () => saveTickers('csp_cc', []),
      removeCsTicker: (ticker) =>
        saveTickers(
          'cs',
          (settings?.ticker_lists.cs ?? []).filter((item) => item !== ticker),
        ),
      clearCsTickers: () => saveTickers('cs', []),
      updateCspFilterDraft: (field, nextValue) => {
        setCspFilterSaveStatus('idle')
        setCspFilterDraft((current) => draftWithField(current, field, nextValue))
      },
      resetCspFilters: () => {
        setCspFilterSaveStatus('idle')
        setCspFilterDraft(filterDraftFromSettings(defaultCspFilters))
      },
      updateCcFilterDraft: (field, nextValue) => {
        setCcFilterSaveStatus('idle')
        setCcFilterDraft((current) => draftWithField(current, field, nextValue))
      },
      resetCcFilters: () => {
        setCcFilterSaveStatus('idle')
        setCcFilterDraft(filterDraftFromSettings(defaultCspFilters))
      },
      updateCsFilterDraft: (field, nextValue) => {
        setCsFilterSaveStatus('idle')
        setCsFilterDraft((current) => draftWithField(current, field, nextValue))
      },
      toggleCsStrategyType: (strategy) => {
        setCsFilterSaveStatus('idle')
        setCsFilterDraft((current) => ({
          ...current,
          strategy_types: toggleValue(current.strategy_types, strategy),
        }))
      },
      toggleCsSpreadWidth: (width) => {
        setCsFilterSaveStatus('idle')
        setCsFilterDraft((current) => ({
          ...current,
          spread_widths: toggleValue(current.spread_widths, width),
        }))
      },
      resetCsFilters: () => {
        setCsFilterSaveStatus('idle')
        setCsFilterDraft(creditSpreadFilterDraftFromSettings(defaultCsFilters))
      },
      startCspScan,
      startCcScan,
      startCsScan,
      cancelActiveScan,
      setCspSort: (key) => setSorts((current) => ({
        ...current,
        csp: nextSort(current.csp, key),
      })),
      setCcSort: (key) => setSorts((current) => ({
        ...current,
        cc: nextSort(current.cc, key),
      })),
      setCsSort: (key) => setSorts((current) => ({
        ...current,
        cs: nextSort(current.cs, key),
      })),
    }),
    [
      addCspTickers,
      addCsTickers,
      cancelActiveScan,
      cspFilterDraft,
      cspFilterSaveStatus,
      confirmedCspFilters,
      ccFilterDraft,
      ccFilterSaveStatus,
      ccValidation.error,
      ccValidation.filters,
      csFilterDraft,
      csFilterSaveStatus,
      csValidation.error,
      csValidation.filters,
      confirmedCcFilters,
      confirmedCsFilters,
      isLoading,
      isTickerUpdatePending,
      loadError,
      saveTickers,
      scanActionError,
      scanState,
      settings,
      sorts,
      startCspScan,
      startCcScan,
      startCsScan,
      tickerSaveError,
      validation.error,
      validation.filters,
    ],
  )

  return (
    <OptionsScreenersContext.Provider value={value}>
      {children}
    </OptionsScreenersContext.Provider>
  )
}

function addTickersToList(
  listName: OptionsScreenerTickerList,
  tickers: string[],
  settings: OptionsScreenerSettingsResponse | null,
  saveTickers: (
    listName: OptionsScreenerTickerList,
    nextTickers: string[],
  ) => Promise<void>,
) {
  const current = settings?.ticker_lists[listName] ?? []
  return saveTickers(listName, [
    ...current,
    ...tickers.filter((item) => !current.includes(item)),
  ])
}

function nextSort<Key extends string>(
  current: SortState<Key>,
  key: Key,
) {
  return {
    key,
    direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
  } as const
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

function draftWithField<Draft extends ScreenerFilterDraft>(
  draft: Draft,
  field: keyof ScreenerFilterDraft,
  value: string,
) {
  return {
    ...draft,
    [field]: value,
  }
}

export function useOptionsScreeners() {
  const context = useContext(OptionsScreenersContext)
  if (!context) {
    throw new Error(
      'useOptionsScreeners must be used within OptionsScreenersProvider.',
    )
  }
  return context
}

function applyScanEvent(
  current: OptionsScreenerScanState,
  event: OptionsScreenerScanEvent,
) {
  const job = event.job
  const activeJob = job.status === 'active' ? job : null
  const completedSnapshot: OptionsScreenerCompletedSnapshot | null =
    job.status === 'completed' && job.successful_completion_at
      ? {
          screener: job.screener,
          job_id: job.id,
          total_match_count: job.total_match_count,
          excluded_contracts: job.excluded_contracts,
          candidates: job.candidates,
          errors: job.errors,
          warnings: job.warnings,
          completed_at: job.successful_completion_at,
        }
      : current.completed_snapshots[job.screener]
  return {
    active_job: activeJob,
    latest_jobs: { ...current.latest_jobs, [job.screener]: job },
    completed_snapshots: {
      ...current.completed_snapshots,
      [job.screener]: completedSnapshot,
    },
  }
}

function sameFilters(
  first: OptionsScreenerFilters,
  second: OptionsScreenerFilters,
) {
  return (
    first.minimum_dte === second.minimum_dte &&
    first.maximum_dte === second.maximum_dte &&
    first.minimum_absolute_delta === second.minimum_absolute_delta &&
    first.maximum_absolute_delta === second.maximum_absolute_delta &&
    first.minimum_annualized_return === second.minimum_annualized_return
  )
}

function useFilterAutosave<Filters extends OptionsScreenerFilters>({
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
  screener: 'csp' | 'cc'
  filters: Filters | null
  confirmedFilters: Filters
  same: (first: Filters, second: Filters) => boolean
  setConfirmedFilters: (filters: Filters) => void
  setSaveStatus: (status: SaveStatus) => void
  setSettings: Dispatch<SetStateAction<OptionsScreenerSettingsResponse | null>>
}): void
function useFilterAutosave<Filters extends CreditSpreadScreenerFilters>({
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
  screener: 'cs'
  filters: Filters | null
  confirmedFilters: Filters
  same: (first: Filters, second: Filters) => boolean
  setConfirmedFilters: (filters: Filters) => void
  setSaveStatus: (status: SaveStatus) => void
  setSettings: Dispatch<SetStateAction<OptionsScreenerSettingsResponse | null>>
}): void
function useFilterAutosave<
  Filters extends OptionsScreenerFilters | CreditSpreadScreenerFilters,
>({
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
  screener: 'csp' | 'cc' | 'cs'
  filters: Filters | null
  confirmedFilters: Filters
  same: (first: Filters, second: Filters) => boolean
  setConfirmedFilters: (filters: Filters) => void
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
      const saveFilters = saveOptionsScreenerFilters as (
        screener: 'csp' | 'cc' | 'cs',
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
      ) => Promise<OptionsScreenerFilters | CreditSpreadScreenerFilters>
      saveFilters(
        screener,
        nextFilters,
      ).then((saved) => {
        if (sequence !== saveSequence.current) {
          return
        }
        const typedSaved = saved as Filters
        setConfirmedFilters(typedSaved)
        setSettings((current) =>
          current
            ? {
                ...current,
                filters: { ...current.filters, [screener]: typedSaved },
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

function sameCreditSpreadFilters(
  first: CreditSpreadScreenerFilters,
  second: CreditSpreadScreenerFilters,
) {
  return (
    sameFilters(first, second) &&
    sameSelection(first.strategy_types, second.strategy_types) &&
    sameSelection(first.spread_widths, second.spread_widths)
  )
}

function sameSelection<Value extends string | number>(
  first: Value[],
  second: Value[],
) {
  if (first.length !== second.length) {
    return false
  }
  return first.every((value) => second.includes(value))
}

function toggleValue<Value extends string | number>(
  values: Value[],
  value: Value,
) {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value]
}

function errorMessage(error: unknown) {
  return requestErrorMessage(error, 'Unexpected screener error.')
}

export function cspCandidates(
  candidates: OptionsScreenerScanJob['candidates'],
) {
  return candidates.filter(
    (candidate): candidate is CashSecuredPutCandidate =>
      candidate.strategy === 'csp',
  )
}

export function ccCandidates(
  candidates: OptionsScreenerScanJob['candidates'],
) {
  return candidates.filter(
    (candidate): candidate is CoveredCallCandidate =>
      candidate.strategy === 'cc',
  )
}

export function csCandidates(
  candidates: OptionsScreenerScanJob['candidates'],
) {
  return candidates.filter(
    (candidate): candidate is CreditSpreadCandidate =>
      candidate.strategy === 'put_credit_spread' ||
      candidate.strategy === 'call_credit_spread',
  )
}
