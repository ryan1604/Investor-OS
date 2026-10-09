import {
  type ReactNode,
  useCallback,
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
  startOptionsScreenerScan,
  type CreditSpreadScreenerFilters,
  type OptionsScreenerTickerList,
  type OptionsScreenerCompletedSnapshot,
  type OptionsScreenerFilters,
  type OptionsScreenerScanEvent,
  type OptionsScreenerScanState,
  type OptionsScreenerSettingsResponse,
} from '@/api/optionsScreeners'
import {
  useScreenerFilterSlice,
} from '@/features/options-screeners/hooks/useScreenerFilterSlice'
import {
  OptionsScreenersContext,
  type CspSortKey,
  type CcSortKey,
  type CsSortKey,
  type OptionsScreenersContextValue,
} from '@/features/options-screeners/hooks/useOptionsScreeners'
import { errorMessage } from '@/lib/errors'
import {
  defaultSingleLegFilters,
  defaultCsFilters,
  creditSpreadFilterDraftFromSettings,
  type CreditSpreadFilterDraft,
  filterDraftFromSettings,
  type ScreenerFilterDraft,
  validateCreditSpreadFilterDraft,
  validateFilterDraft,
} from '@/features/options-screeners/lib/screenerSettings'

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
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tickerSaveError, setTickerSaveError] = useState<string | null>(null)
  const [isTickerUpdatePending, setIsTickerUpdatePending] = useState(false)
  const [scanActionError, setScanActionError] = useState<string | null>(null)
  const [filtersInitialized, setFiltersInitialized] = useState(false)
  const confirmedTickersRef = useRef<Record<OptionsScreenerTickerList, string[]>>({
    csp_cc: [],
    cs: [],
  })
  const csp = useScreenerFilterSlice<'csp', CspSortKey, ScreenerFilterDraft>({
    screener: 'csp',
    initialized: filtersInitialized,
    setSettings,
    defaultFilters: defaultSingleLegFilters,
    draftFromSettings: filterDraftFromSettings,
    validate: validateFilterDraft,
    same: sameFilters,
    initialSort: { key: 'annualized_return', direction: 'desc' },
  })
  const cc = useScreenerFilterSlice<'cc', CcSortKey, ScreenerFilterDraft>({
    screener: 'cc',
    initialized: filtersInitialized,
    setSettings,
    defaultFilters: defaultSingleLegFilters,
    draftFromSettings: filterDraftFromSettings,
    validate: validateFilterDraft,
    same: sameFilters,
    initialSort: { key: 'annualized_return', direction: 'desc' },
  })
  const cs = useScreenerFilterSlice<'cs', CsSortKey, CreditSpreadFilterDraft>({
    screener: 'cs',
    initialized: filtersInitialized,
    setSettings,
    defaultFilters: defaultCsFilters,
    draftFromSettings: creditSpreadFilterDraftFromSettings,
    validate: validateCreditSpreadFilterDraft,
    same: sameCreditSpreadFilters,
    initialSort: { key: 'annualized_return', direction: 'desc' },
  })
  const { initialize: initializeCsp, slice: cspSlice } = csp
  const { initialize: initializeCc, slice: ccSlice } = cc
  const { initialize: initializeCs, slice: csSlice, updateDraft: updateCsDraft } = cs

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
        initializeCsp(nextSettings.filters.csp)
        initializeCc(nextSettings.filters.cc)
        initializeCs(nextSettings.filters.cs)
        setFiltersInitialized(true)
        setLoadError(null)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(errorMessage(error, 'Unexpected screener error.'))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      })
    return () => controller.abort()
  }, [initializeCsp, initializeCc, initializeCs])

  useEffect(() => {
    if (isLoading) {
      return
    }
    if (typeof WebSocket === 'undefined') {
      return
    }
    const socket = new WebSocket(getOptionsScreenerScansWsUrl())
    socket.onmessage = (event) => {
      const update: OptionsScreenerScanEvent = JSON.parse(event.data)
      setScanState((current) => applyScanEvent(current, update))
    }
    return () => socket.close()
  }, [isLoading])

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
      setTickerSaveError(errorMessage(error, 'Unexpected screener error.'))
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
      setScanActionError(errorMessage(error, 'Unexpected screener error.'))
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
      setScanActionError(errorMessage(error, 'Unexpected screener error.'))
    }
  }, [scanState.active_job])

  const value = useMemo<OptionsScreenersContextValue>(
    () => {
      const sharedTickers = {
        tickers: settings?.ticker_lists.csp_cc ?? [],
        addTickers: addCspTickers,
        removeTicker: (ticker: string) => saveTickers(
          'csp_cc',
          (settings?.ticker_lists.csp_cc ?? []).filter((item) => item !== ticker),
        ),
        clearTickers: () => saveTickers('csp_cc', []),
      }
      return {
        isLoading,
        loadError,
        tickerSaveError,
        isTickerUpdatePending,
        scanActionError,
        activeJob: scanState.active_job,
        cancelActiveScan,
        screeners: {
          csp: {
            ...cspSlice,
            ...sharedTickers,
            latestJob: scanState.latest_jobs.csp,
            snapshot: scanState.completed_snapshots.csp,
            startScan: startCspScan,
          },
          cc: {
            ...ccSlice,
            ...sharedTickers,
            latestJob: scanState.latest_jobs.cc,
            snapshot: scanState.completed_snapshots.cc,
            startScan: startCcScan,
          },
          cs: {
            ...csSlice,
            tickers: settings?.ticker_lists.cs ?? [],
            latestJob: scanState.latest_jobs.cs,
            snapshot: scanState.completed_snapshots.cs,
            addTickers: addCsTickers,
            removeTicker: (ticker) => saveTickers(
              'cs',
              (settings?.ticker_lists.cs ?? []).filter((item) => item !== ticker),
            ),
            clearTickers: () => saveTickers('cs', []),
            startScan: startCsScan,
            toggleStrategyType: (strategy) => updateCsDraft((current) => ({
              ...current,
              strategy_types: toggleValue(current.strategy_types, strategy),
            })),
            toggleSpreadWidth: (width) => updateCsDraft((current) => ({
              ...current,
              spread_widths: toggleValue(current.spread_widths, width),
            })),
          },
        },
      }
    },
    [
      cspSlice,
      ccSlice,
      csSlice,
      updateCsDraft,
      settings,
      scanState,
      isLoading,
      loadError,
      tickerSaveError,
      isTickerUpdatePending,
      scanActionError,
      addCspTickers,
      addCsTickers,
      saveTickers,
      startCspScan,
      startCcScan,
      startCsScan,
      cancelActiveScan,
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
