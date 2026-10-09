import { useCallback, useEffect, useRef, useState } from 'react'

import { isAbortError } from '@/api/client'
import { errorMessage } from '@/lib/errors'
import {
  fetchRiskLimits,
  saveRiskLimits,
  type RiskLimit,
  type RiskLimitKey,
} from '@/api/portfolioAnalysis'

type LoadedLimits = {
  account: string | null
  limits: RiskLimit[]
}

export function useRiskLimits(account: string | null) {
  const [loaded, setLoaded] = useState<LoadedLimits>({ account: null, limits: [] })
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The selected account, read by saves that finish after a switch.
  const accountRef = useRef(account)

  useEffect(() => {
    accountRef.current = account
    if (!account) {
      return
    }
    const controller = new AbortController()
    fetchRiskLimits(account, controller.signal)
      .then((response) => {
        setLoaded({ account, limits: response.limits })
        setError(null)
      })
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(errorMessage(requestError, 'Risk limits request failed'))
        }
      })
    return () => controller.abort()
  }, [account])

  const save = useCallback(
    async (limits: Partial<Record<RiskLimitKey, number>>) => {
      if (!account) {
        return false
      }
      setIsSaving(true)
      setError(null)
      try {
        const response = await saveRiskLimits(account, limits)
        // A save for an account the user has left must not replace the current one's limits.
        if (accountRef.current === account) {
          setLoaded({ account, limits: response.limits })
        }
        return true
      } catch (requestError) {
        if (accountRef.current === account) {
          setError(errorMessage(requestError, 'Risk limits request failed'))
        }
        return false
      } finally {
        setIsSaving(false)
      }
    },
    [account],
  )

  // Limits loaded for another account are never shown against this one.
  const limits = loaded.account === account ? loaded.limits : []
  return { limits, isLoaded: loaded.account === account, isSaving, error, save }
}
