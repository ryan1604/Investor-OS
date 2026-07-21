import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchPortfolioChartValues,
  replacePortfolioChartValues,
  type PortfolioChartValueRequest,
  type PortfolioChartValue,
} from '@/api/portfolioChartValues'
import { errorMessage, isAbortError } from '@/api/client'

function portfolioChartValuesErrorMessage(error: unknown) {
  return errorMessage(error, 'Portfolio chart values request failed')
}

export function usePortfolioChartValues(account: string | undefined) {
  const [state, setState] = useState<{
    account: string | undefined
    rows: PortfolioChartValue[]
    isLoading: boolean
    isSaving: boolean
    error: string | null
  }>({
    account: undefined,
    rows: [],
    isLoading: false,
    isSaving: false,
    error: null,
  })
  const accountRef = useRef(account)
  const requestGenerationRef = useRef(0)
  const saveControllerRef = useRef<AbortController | null>(null)
  accountRef.current = account

  useEffect(() => {
    const requestGeneration = ++requestGenerationRef.current
    saveControllerRef.current?.abort()
    saveControllerRef.current = null

    if (!account) {
      setState({
        account: undefined,
        rows: [],
        isLoading: false,
        isSaving: false,
        error: null,
      })
      return
    }

    const controller = new AbortController()
    setState({
      account,
      rows: [],
      isLoading: true,
      isSaving: false,
      error: null,
    })

    fetchPortfolioChartValues(account, controller.signal)
      .then((response) => {
        if (
          requestGenerationRef.current === requestGeneration &&
          accountRef.current === account
        ) {
          setState({
            account,
            rows: response.rows,
            isLoading: false,
            isSaving: false,
            error: null,
          })
        }
      })
      .catch((requestError: unknown) => {
        if (
          !isAbortError(requestError) &&
          requestGenerationRef.current === requestGeneration &&
          accountRef.current === account
        ) {
          setState({
            account,
            rows: [],
            isLoading: false,
            isSaving: false,
            error: portfolioChartValuesErrorMessage(requestError),
          })
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

      const requestGeneration = requestGenerationRef.current
      const saveController = new AbortController()
      saveControllerRef.current?.abort()
      saveControllerRef.current = saveController
      setState((currentState) =>
        currentState.account === account
          ? { ...currentState, isSaving: true, error: null }
          : currentState,
      )

      try {
        const response = await replacePortfolioChartValues(account, {
          rows: nextRows,
        }, saveController.signal)
        if (
          requestGenerationRef.current === requestGeneration &&
          accountRef.current === account
        ) {
          setState({
            account,
            rows: response.rows,
            isLoading: false,
            isSaving: false,
            error: null,
          })
        }
        return response.rows
      } catch (requestError) {
        if (
          !isAbortError(requestError) &&
          requestGenerationRef.current === requestGeneration &&
          accountRef.current === account
        ) {
          setState((currentState) =>
            currentState.account === account
              ? {
                  ...currentState,
                  isSaving: false,
                  error: portfolioChartValuesErrorMessage(requestError),
                }
              : currentState,
          )
        }
        throw requestError
      } finally {
        if (saveControllerRef.current === saveController) {
          saveControllerRef.current = null
        }
      }
    },
    [account],
  )

  const isCurrentAccount = state.account === account

  return {
    rows: account && isCurrentAccount ? state.rows : [],
    isLoading: account ? !isCurrentAccount || state.isLoading : false,
    isSaving: account && isCurrentAccount ? state.isSaving : false,
    error: account && isCurrentAccount ? state.error : null,
    saveRows,
  }
}
