import { useCallback, useEffect, useState } from 'react'

import { errorMessage, isAbortError } from '@/api/client'
import {
  deleteBetaOverride,
  fetchBetaOverrides,
  saveBetaOverride,
  type BetaOverride,
} from '@/api/portfolioAnalysis'

export function useBetaOverrides(onChange: () => void) {
  const [overrides, setOverrides] = useState<BetaOverride[]>([])
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchBetaOverrides(controller.signal)
      .then(setOverrides)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(errorMessage(requestError, 'Beta overrides request failed'))
        }
      })
    return () => controller.abort()
  }, [])

  const run = useCallback(
    async (change: () => Promise<(current: BetaOverride[]) => BetaOverride[]>) => {
      setIsSaving(true)
      setError(null)
      try {
        const update = await change()
        setOverrides(update)
        onChange()
        return true
      } catch (requestError) {
        setError(errorMessage(requestError, 'Beta override request failed'))
        return false
      } finally {
        setIsSaving(false)
      }
    },
    [onChange],
  )

  const save = useCallback(
    (ticker: string, beta: number) =>
      run(async () => {
        const saved = await saveBetaOverride(ticker, beta)
        return (current) =>
          [...current.filter((item) => item.ticker !== saved.ticker), saved].sort(
            (first, second) => first.ticker.localeCompare(second.ticker),
          )
      }),
    [run],
  )

  const remove = useCallback(
    (ticker: string) =>
      run(async () => {
        await deleteBetaOverride(ticker)
        return (current) => current.filter((item) => item.ticker !== ticker)
      }),
    [run],
  )

  return { overrides, isSaving, error, save, remove }
}
