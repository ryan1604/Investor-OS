import { useEffect, useMemo, useRef, useState } from 'react'

import { toast } from 'sonner'

import {
  deleteStockAnalysisModel,
  fetchStockAnalysisCurrentPrice,
  fetchStockAnalysisModel,
  upsertStockAnalysisModel,
  type StockAnalysisPayload,
} from '@/api/stockAnalysis'
import { errorMessage as requestErrorMessage, isAbortError } from '@/api/client'
import type { EditingCell } from '@/features/stock-analysis/components/ScenarioValuationTable'
import {
  calculateValuationModel,
  createEmptyValuationModel,
  SCENARIO_KEYS,
  stockAnalysisValuationModelFromPayload,
  type EditableRowKey,
  type ScenarioKey,
  type StockAnalysisValuationModel,
  type ValuationYearValues,
  type YearIndex,
} from '@/features/stock-analysis/lib/valuationModel'

export type SaveStatus = 'idle' | 'loading' | 'saved' | 'saving' | 'unsaved' | 'error'

type ActiveModel = {
  ticker: string
  version: number
  valuation: StockAnalysisValuationModel
}

export function useStockAnalysisModel() {
  const [tickerSearch, setTickerSearch] = useState('')
  const [activeModel, setActiveModel] = useState<ActiveModel | null>(null)
  const [firstForecastYearInput, setFirstForecastYearInput] = useState('')
  const [currentPriceStatus, setCurrentPriceStatus] = useState<
    'idle' | 'loading' | 'loaded' | 'unavailable'
  >('idle')
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [isDeleting, setIsDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const saveGenerationRef = useRef(0)
  const loadRequestControllerRef = useRef<AbortController | null>(null)
  const saveRequestControllerRef = useRef<AbortController | null>(null)
  const savePromisesRef = useRef(new Set<Promise<void>>())
  const deleteRequestControllerRef = useRef<AbortController | null>(null)
  const deleteInProgressRef = useRef(false)

  const calculatedModel = useMemo(
    () =>
      activeModel
        ? calculateValuationModel(activeModel.valuation)
        : calculateValuationModel(createEmptyValuationModel()),
    [activeModel],
  )

  useEffect(() => {
    return () => {
      loadRequestControllerRef.current?.abort()
      saveRequestControllerRef.current?.abort()
      deleteRequestControllerRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (!activeModel || !hasUnsavedChanges) {
      return
    }

    const saveGeneration = saveGenerationRef.current
    const saveController = new AbortController()
    let saveStarted = false
    saveRequestControllerRef.current?.abort()
    saveRequestControllerRef.current = saveController
    const saveTimer = window.setTimeout(() => {
      if (deleteInProgressRef.current) {
        return
      }

      saveStarted = true
      setSaveStatus('saving')
      const savePromise = upsertStockAnalysisModel(activeModel.ticker, {
        version: activeModel.version,
        payload: toStockAnalysisPayload(activeModel.valuation),
      }, saveController.signal)
        .then((savedModel) => {
          if (saveGenerationRef.current !== saveGeneration) {
            return
          }

          setActiveModel((currentModel) =>
            currentModel && currentModel.ticker === savedModel.ticker
              ? { ...currentModel, version: savedModel.version }
              : currentModel,
          )
          setHasUnsavedChanges(false)
          setSaveStatus('saved')
          setError(null)
        })
        .catch((requestError) => {
          if (isAbortError(requestError)) {
            return
          }

          if (saveGenerationRef.current !== saveGeneration) {
            return
          }

          setSaveStatus('error')
          setError(errorMessage(requestError))
        })
        .finally(() => {
          savePromisesRef.current.delete(savePromise)
        })
      savePromisesRef.current.add(savePromise)
    }, 700)

    return () => {
      window.clearTimeout(saveTimer)
      if (saveRequestControllerRef.current === saveController) {
        saveRequestControllerRef.current = null
      }
      if (!saveStarted) {
        saveController.abort()
      }
    }
  }, [activeModel, hasUnsavedChanges])

  async function handleTickerSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const ticker = normalizeTicker(tickerSearch)
    if (!ticker) {
      return
    }

    setTickerSearch(ticker)
    setSaveStatus('loading')
    setCurrentPriceStatus('loading')
    setError(null)
    setHasUnsavedChanges(false)
    saveGenerationRef.current += 1
    loadRequestControllerRef.current?.abort()
    saveRequestControllerRef.current?.abort()
    deleteRequestControllerRef.current?.abort()
    const loadController = new AbortController()
    loadRequestControllerRef.current = loadController

    try {
      const [savedModel, currentPriceResult] = await Promise.allSettled([
        fetchStockAnalysisModel(ticker, loadController.signal),
        fetchStockAnalysisCurrentPrice(ticker, loadController.signal),
      ])

      if (savedModel.status === 'rejected') {
        throw savedModel.reason
      }

      const valuation = stockAnalysisValuationModelFromPayload(
        savedModel.value.payload,
        savedModel.value.current_price,
      )
      if (currentPriceResult.status === 'fulfilled') {
        valuation.currentPrice = currentPriceResult.value.current_price
        setCurrentPriceStatus('loaded')
      } else {
        setCurrentPriceStatus('unavailable')
      }

      setActiveModel({
        ticker: savedModel.value.ticker,
        version: savedModel.value.version,
        valuation,
      })
      setFirstForecastYearInput(formatFirstForecastYearInput(valuation))
      setSaveStatus(savedModel.value.updated_at ? 'saved' : 'idle')
    } catch (requestError) {
      if (isAbortError(requestError)) {
        return
      }

      const valuation = createEmptyValuationModel()
      setActiveModel({
        ticker,
        version: 1,
        valuation,
      })
      setFirstForecastYearInput('')
      setCurrentPriceStatus('unavailable')
      setSaveStatus('error')
      setError(errorMessage(requestError))
    } finally {
      if (loadRequestControllerRef.current === loadController) {
        loadRequestControllerRef.current = null
      }
    }
  }

  function updateValuationModel(
    updater: (model: StockAnalysisValuationModel) => StockAnalysisValuationModel,
  ) {
    setActiveModel((currentModel) =>
      currentModel
        ? {
            ...currentModel,
            valuation: updater(currentModel.valuation),
          }
        : currentModel,
    )
    saveGenerationRef.current += 1
    setHasUnsavedChanges(true)
    setSaveStatus('unsaved')
  }

  function updateFirstForecastYear(value: string) {
    const nextValue = value.replace(/\D/g, '').slice(0, 4)
    setFirstForecastYearInput(nextValue)
    updateValuationModel((model) => ({
      ...model,
      firstForecastYear: parseFirstForecastYear(nextValue),
    }))
  }

  function commitCellDraft(
    scenario: ScenarioKey,
    row: EditableRowKey,
    yearIndex: YearIndex,
    value: string,
  ) {
    setEditingCell(null)
    updateValuationModel((model) =>
      updateScenarioInput(model, scenario, row, yearIndex, value),
    )
  }

  async function deleteActiveModel() {
    if (!activeModel) {
      return false
    }

    const ticker = activeModel.ticker
    const previousHasUnsavedChanges = hasUnsavedChanges
    const previousSaveStatus = saveStatus
    const deleteController = new AbortController()
    deleteInProgressRef.current = true
    saveGenerationRef.current += 1
    loadRequestControllerRef.current?.abort()
    deleteRequestControllerRef.current?.abort()
    deleteRequestControllerRef.current = deleteController
    setIsDeleting(true)
    setError(null)
    setEditingCell(null)
    setHasUnsavedChanges(false)

    try {
      await Promise.allSettled([...savePromisesRef.current])
      await deleteStockAnalysisModel(ticker, deleteController.signal)
      setActiveModel(null)
      setTickerSearch('')
      setFirstForecastYearInput('')
      setCurrentPriceStatus('idle')
      setSaveStatus('idle')
      toast.success(`${ticker} valuation model deleted.`)
      return true
    } catch (requestError) {
      if (isAbortError(requestError)) {
        return false
      }

      setHasUnsavedChanges(previousHasUnsavedChanges)
      setSaveStatus(previousSaveStatus)
      setError(errorMessage(requestError))
      return false
    } finally {
      deleteInProgressRef.current = false
      if (deleteRequestControllerRef.current === deleteController) {
        deleteRequestControllerRef.current = null
      }
      setIsDeleting(false)
    }
  }

  return {
    activeModel,
    calculatedModel,
    commitCellDraft,
    currentPriceStatus,
    deleteActiveModel,
    editingCell,
    error,
    firstForecastYearInput,
    handleTickerSubmit,
    isDeleting,
    saveStatus,
    setEditingCell,
    setTickerSearch,
    tickerSearch,
    updateFirstForecastYear,
  }
}

export function normalizeTickerInput(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9.-]/g, '')
}

function normalizeTicker(value: string) {
  return normalizeTickerInput(value.trim())
}

function parseFirstForecastYear(value: string) {
  const normalizedValue = value.replace(/\D/g, '').slice(0, 4)

  return normalizedValue.length === 4 ? Number(normalizedValue) : null
}

function parseCellValue(value: string) {
  const trimmedValue = value.replace(/[$,%]/g, '').replaceAll(',', '').trim()
  if (!trimmedValue) {
    return null
  }

  const parsedValue = Number(trimmedValue)
  return Number.isFinite(parsedValue) ? parsedValue : null
}

function formatFirstForecastYearInput(model: StockAnalysisValuationModel) {
  return model.firstForecastYear === null ? '' : String(model.firstForecastYear)
}

function updateScenarioInput(
  model: StockAnalysisValuationModel,
  scenario: ScenarioKey,
  row: EditableRowKey,
  yearIndex: YearIndex,
  value: string,
): StockAnalysisValuationModel {
  const parsedValue = parseCellValue(value)

  if (yearIndex === 0 && !isScenarioSpecificFirstYearRow(row)) {
    return {
      ...model,
      scenarios: Object.fromEntries(
        SCENARIO_KEYS.map((scenarioKey) => [
          scenarioKey,
          {
            ...model.scenarios[scenarioKey],
            [row]: model.scenarios[scenarioKey][row].map((currentValue, index) =>
              index === yearIndex ? parsedValue : currentValue,
            ) as ValuationYearValues,
          },
        ]),
      ) as StockAnalysisValuationModel['scenarios'],
    }
  }

  return {
    ...model,
    scenarios: {
      ...model.scenarios,
      [scenario]: {
        ...model.scenarios[scenario],
        [row]: model.scenarios[scenario][row].map((currentValue, index) =>
          index === yearIndex ? parsedValue : currentValue,
        ) as ValuationYearValues,
      },
    },
  }
}

function isScenarioSpecificFirstYearRow(row: EditableRowKey) {
  return (
    row === 'priceToSales' ||
    row === 'peEstimateLow' ||
    row === 'priceToEbitda' ||
    row === 'priceToOperatingCashFlow' ||
    row === 'priceToFreeCashFlow'
  )
}

function toStockAnalysisPayload(
  model: StockAnalysisValuationModel,
): StockAnalysisPayload {
  return {
    firstForecastYear: model.firstForecastYear,
    ...model.scenarios,
  }
}

function errorMessage(error: unknown) {
  return requestErrorMessage(error, 'Stock analysis request failed.')
}
