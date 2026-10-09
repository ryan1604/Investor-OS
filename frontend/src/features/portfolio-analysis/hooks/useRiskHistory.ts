import { useEffect, useState } from 'react'

import { isAbortError } from '@/api/client'
import { errorMessage } from '@/lib/errors'
import { fetchRiskHistory, type AnalysisRiskSnapshot } from '@/api/portfolioAnalysis'

// Snapshots are written at most once a minute while the page is open.
const REFRESH_MS = 60_000

type LoadedHistory = {
  account: string | null
  snapshots: AnalysisRiskSnapshot[]
}

export function useRiskHistory(account: string | null) {
  const [loaded, setLoaded] = useState<LoadedHistory>({ account: null, snapshots: [] })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!account) {
      return
    }
    let controller = new AbortController()
    const load = () => {
      controller.abort()
      controller = new AbortController()
      fetchRiskHistory(account, controller.signal)
        .then((response) => {
          setLoaded({ account, snapshots: response.snapshots })
          setError(null)
        })
        .catch((requestError: unknown) => {
          if (!isAbortError(requestError)) {
            setError(errorMessage(requestError, 'Risk history request failed'))
          }
        })
    }
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => {
      window.clearInterval(timer)
      controller.abort()
    }
  }, [account])

  // History loaded for another account is never shown against this one.
  const isLoaded = loaded.account === account
  return { snapshots: isLoaded ? loaded.snapshots : [], isLoaded, error }
}
