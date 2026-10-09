import { useCallback, useEffect, useRef, useState } from 'react'

import {
  PORTFOLIO_WS_URL,
  fetchPortfolio,
  type PortfolioResponse,
} from '@/api/portfolio'
import { errorMessage } from '@/lib/errors'
import { connectWithBackoff } from '@/lib/connectWithBackoff'

function portfolioErrorMessage(error: unknown) {
  return errorMessage(error, 'Portfolio request failed')
}

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const isRequestInFlight = useRef(false)

  const loadPortfolio = useCallback(async () => {
    if (isRequestInFlight.current) {
      return
    }

    isRequestInFlight.current = true
    setIsLoading(true)
    setError(null)

    try {
      setPortfolio(await fetchPortfolio())
    } catch (requestError) {
      setError(portfolioErrorMessage(requestError))
    } finally {
      isRequestInFlight.current = false
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let hasSnapshot = false

    return connectWithBackoff(PORTFOLIO_WS_URL, {
      onMessage: (event) => {
        hasSnapshot = true
        setPortfolio(JSON.parse(event.data) as PortfolioResponse)
        setError(null)
        setIsLoading(false)
      },
      onError: () => {
        setError('Portfolio stream disconnected.')
        if (!hasSnapshot) {
          setIsLoading(false)
        }
      },
      onClose: () => {
        setError('Portfolio stream disconnected.')
        if (!hasSnapshot) {
          setIsLoading(false)
        }
      },
    })
  }, [])

  return {
    portfolio,
    isLoading,
    error,
    loadPortfolio,
  }
}
