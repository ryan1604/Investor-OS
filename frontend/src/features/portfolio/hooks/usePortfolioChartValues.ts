import { useCallback, useEffect, useState } from 'react'

import {
  fetchPortfolioChartValues,
  replacePortfolioChartValues,
  type PortfolioChartValueRequest,
  type PortfolioChartValue,
} from '@/api/portfolioChartValues'
import { isAbortError } from '@/api/client'

function portfolioChartValuesErrorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : 'Portfolio chart values request failed'
}

export function usePortfolioChartValues(account: string | undefined) {
  const [rows, setRows] = useState<PortfolioChartValue[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!account) {
      return
    }

    const controller = new AbortController()

    Promise.resolve().then(() => {
      if (!controller.signal.aborted) {
        setIsLoading(true)
        setError(null)
      }
    })

    fetchPortfolioChartValues(account, controller.signal)
      .then((response) => {
        setRows(response.rows)
      })
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(portfolioChartValuesErrorMessage(requestError))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      })

    return () => {
      controller.abort()
    }
  }, [account])

  const saveRows = useCallback(
    async (nextRows: PortfolioChartValueRequest[]) => {
      if (!account) {
        throw new Error('Account is required.')
      }

      setIsSaving(true)
      setError(null)

      try {
        const response = await replacePortfolioChartValues(account, {
          rows: nextRows,
        })
        setRows(response.rows)
        return response.rows
      } catch (requestError) {
        const message = portfolioChartValuesErrorMessage(requestError)
        setError(message)
        throw requestError
      } finally {
        setIsSaving(false)
      }
    },
    [account],
  )

  return {
    rows: account ? rows : [],
    isLoading: account ? isLoading : false,
    isSaving: account ? isSaving : false,
    error: account ? error : null,
    saveRows,
  }
}
