// @vitest-environment jsdom

import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import type { PortfolioResponse } from '@/api/portfolio'
import { useSelectedAccount } from './useSelectedAccount'

afterEach(cleanup)

it('selects the first saved account on an offline cold start', () => {
  const { result } = renderHook(() => useSelectedAccount(null, null, ['DU2', 'DU1']))
  expect(result.current.activeAccount).toBe('DU1')
  expect(result.current.accounts).toEqual(['DU1','DU2'])
})

it('retains the selected history account when the live snapshot disappears', () => {
  const { result, rerender } = renderHook(
    ({ portfolio }: { portfolio: PortfolioResponse | null }) =>
      useSelectedAccount(portfolio, 'DU1'),
    { initialProps: { portfolio: null as PortfolioResponse | null } },
  )
  expect(result.current.activeAccount).toBe('DU1')
  expect(result.current.accounts).toEqual(['DU1'])
  expect(result.current.accountPositions).toEqual([])
  expect(result.current.activeAccountSummary).toBeNull()
  rerender({ portfolio: {
    status: { connected: false, host: '', port: 7497, client_id: 1 },
    accounts: [], positions: [], message: null,
  } })
  expect(result.current.activeAccount).toBe('DU1')
})

it('does not retain an unavailable account when connected', () => {
  const { result } = renderHook(() => useSelectedAccount({
    status: { connected: true, host: '', port: 7497, client_id: 1 },
    accounts: [], positions: [], message: null,
  }, 'DU1'))
  expect(result.current.activeAccount).toBeUndefined()
})
