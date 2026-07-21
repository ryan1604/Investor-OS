import { useEffect, useRef, useState, type FormEvent } from 'react'

import { errorMessage as requestErrorMessage, isAbortError } from '@/api/client'
import {
  fetchOptionExpirations,
  fetchOptionsAnalysis,
  type OptionExpiration,
  type OptionsAnalysisResponse,
} from '@/api/options'

export function errorMessage(error: unknown) {
  return requestErrorMessage(error, 'Options request failed.')
}

export function hasAnalysisPriceData(analysis: OptionsAnalysisResponse) {
  return analysis.candles.length > 0 && analysis.underlying_price !== null
}

export function useOptionsAnalysis() {
  const [ticker, setTicker] = useState('')
  const [analysis, setAnalysis] = useState<OptionsAnalysisResponse | null>(null)
  const [expirations, setExpirations] = useState<OptionExpiration[]>([])
  const [selectedExpiration, setSelectedExpiration] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isExpirationsLoading, setIsExpirationsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expirationsError, setExpirationsError] = useState<string | null>(null)
  const analysisRequestIdRef = useRef(0)
  const activeRequestControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      activeRequestControllerRef.current?.abort()
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const normalizedTicker = ticker.trim().toUpperCase()
    const requestId = analysisRequestIdRef.current + 1
    activeRequestControllerRef.current?.abort()
    const requestController = new AbortController()
    activeRequestControllerRef.current = requestController
    analysisRequestIdRef.current = requestId
    setTicker(normalizedTicker)
    setAnalysis(null)
    setExpirations([])
    setSelectedExpiration('')
    setExpirationsError(null)
    setIsExpirationsLoading(false)

    if (!normalizedTicker) {
      setError('Ticker is required.')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const nextAnalysis = await fetchOptionsAnalysis(
        normalizedTicker,
        requestController.signal,
      )
      if (analysisRequestIdRef.current !== requestId) {
        return
      }

      setAnalysis(nextAnalysis)
    } catch (nextError) {
      if (isAbortError(nextError)) {
        return
      }

      if (analysisRequestIdRef.current !== requestId) {
        return
      }

      setAnalysis(null)
      setError(errorMessage(nextError))
      return
    } finally {
      if (analysisRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }

    if (analysisRequestIdRef.current !== requestId) {
      return
    }

    setIsExpirationsLoading(true)

    try {
      const nextExpirations = await fetchOptionExpirations(
        normalizedTicker,
        requestController.signal,
      )
      if (analysisRequestIdRef.current !== requestId) {
        return
      }

      setExpirations(nextExpirations.expirations)
      setSelectedExpiration(
        nextExpirations.selected_expiration ??
          nextExpirations.expirations[0]?.date ??
          '',
      )
    } catch (nextError) {
      if (isAbortError(nextError)) {
        return
      }

      if (analysisRequestIdRef.current === requestId) {
        setExpirationsError(errorMessage(nextError))
      }
    } finally {
      if (analysisRequestIdRef.current === requestId) {
        setIsExpirationsLoading(false)
      }
    }
  }

  return {
    analysis,
    error,
    expirations,
    expirationsError,
    handleSubmit,
    isExpirationsLoading,
    isLoading,
    selectedExpiration,
    setSelectedExpiration,
    setTicker,
    ticker,
  }
}
