import { useEffect, useState } from 'react'
import { fetchNav, fetchNavAccounts, type NavHistory } from '@/api/portfolioNav'
import { errorMessage } from '@/api/client'

export function useNavHistory(account: string | undefined) {
  const [state, setState] = useState<{ account?: string; data: NavHistory | null; error: string | null }>({ data: null, error: null })
  useEffect(() => {
    if (!account) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function load() {
      try {
        const data = await fetchNav(account!, controller.signal)
        if (data.account !== account) throw new Error('Account mismatch in NAV history.')
        if (!controller.signal.aborted) setState({ account, data, error: null })
      } catch (error) {
        if (!controller.signal.aborted) setState(previous => ({
          account, data: previous.account === account ? previous.data : null,
          error: errorMessage(error, 'Could not refresh NAV history.'),
        }))
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => void load(), 30_000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [account])
  const current = state.account === account
  return { data: current ? state.data : null, error: current ? state.error : null,
    isLoading: Boolean(account) && (!current || (!state.data && !state.error)) }
}

export function useNavAccounts() {
  const [accounts, setAccounts] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function load() {
      try {
        const result = await fetchNavAccounts(controller.signal)
        if (!controller.signal.aborted) { setAccounts(result); setError(null) }
      } catch (failure) {
        if (!controller.signal.aborted) setError(errorMessage(failure, 'Could not load saved accounts.'))
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => void load(), 30_000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [])
  return { accounts, error }
}
