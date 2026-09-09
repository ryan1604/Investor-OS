// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useNavHistory, useNavAccounts } from './useNavHistory'
import type { NavHistory } from '@/api/portfolioNav'

const mocks = vi.hoisted(() => ({ fetchNav: vi.fn(), fetchNavAccounts: vi.fn() }))
vi.mock('@/api/portfolioNav', () => mocks)
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks() })
const history = (account: string): NavHistory => ({ account, rows: [], latest_report_date: null, currencies: [], currency_changed: false, sync: { configured: false, state: 'unconfigured', error: null, last_successful_sync: null } })

it('ignores late responses after switching accounts', async () => {
  let resolve!: (data: NavHistory) => void
  mocks.fetchNav.mockReturnValueOnce(new Promise<NavHistory>(r => { resolve = r })).mockResolvedValueOnce(history('DU2'))
  const { result, rerender } = renderHook(({ account }) => useNavHistory(account), { initialProps: { account: 'DU1' } })
  rerender({ account: 'DU2' })
  expect(result.current.data).toBeNull()
  await waitFor(() => expect(result.current.data?.account).toBe('DU2'))
  await act(async () => resolve(history('DU1')))
  expect(result.current.data?.account).toBe('DU2')
  expect(mocks.fetchNav.mock.calls[0][1].aborted).toBe(true)
})

it('keeps cached history after a polling failure', async () => {
  vi.useFakeTimers()
  mocks.fetchNav.mockResolvedValueOnce(history('DU1')).mockRejectedValueOnce(new Error('Offline'))
  const { result } = renderHook(() => useNavHistory('DU1'))
  await act(async () => { await Promise.resolve() })
  expect(result.current.data?.account).toBe('DU1')
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
  expect(result.current.error).toBe('Offline')
  expect(result.current.data?.account).toBe('DU1')
})

it('loads saved accounts independently of TWS', async () => {
  mocks.fetchNavAccounts.mockResolvedValue(['DU1','DU2'])
  const { result } = renderHook(useNavAccounts)
  await waitFor(() => expect(result.current.accounts).toEqual(['DU1','DU2']))
})
