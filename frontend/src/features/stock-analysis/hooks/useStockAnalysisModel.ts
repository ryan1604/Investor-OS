import { useEffect, useMemo, useRef, useState } from 'react'

import {
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
  const [error, setError] = useState<string | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const saveGenerationRef = useRef(0)
  const loadRequestControllerRef = useRef<AbortController | null>(null)
  const saveRequestControllerRef = useRef<AbortController | null>(null)

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
    }
  }, [])

  useEffect(() => {
    if (!activeModel || !hasUnsavedChanges) {
      return
    }

    const saveGeneration = saveGenerationRef.current
    const saveController = new AbortController()
    saveRequestControllerRef.current?.abort()
    saveRequestControllerRef.current = saveController
    const saveTimer = window.setTimeout(() => {
      setSaveStatus('saving')
      void upsertStockAnalysisModel(activeModel.ticker, {
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
    }, 700)

    return () => {
      window.clearTimeout(saveTimer)
      if (saveRequestControllerRef.current === saveController) {
        saveRequestControllerRef.current = null
      }
      saveController.abort()
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

  return {
    activeModel,
    calculatedModel,
    commitCellDraft,
    currentPriceStatus,
    editingCell,
    error,
    firstForecastYearInput,
    handleTickerSubmit,
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
  return {
    ...model,
    scenarios: {
      ...model.scenarios,
      [scenario]: {
        ...model.scenarios[scenario],
        [row]: model.scenarios[scenario][row].map((currentValue, index) =>
          index === yearIndex ? parseCellValue(value) : currentValue,
        ) as ValuationYearValues,
      },
    },
  }
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
