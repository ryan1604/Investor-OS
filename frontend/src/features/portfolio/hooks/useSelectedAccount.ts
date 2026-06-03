import { useMemo } from 'react'

import type { PortfolioResponse } from '@/api/portfolio'

export function useSelectedAccount(
  portfolio: PortfolioResponse | null,
  selectedAccount: string | null,
) {
  const accounts = useMemo(() => {
    return Array.from(
      new Set([
        ...(portfolio?.accounts.map((account) => account.account) ?? []),
        ...(portfolio?.positions.map((position) => position.account) ?? []),
      ]),
    ).sort()
  }, [portfolio])

  const activeAccount =
    selectedAccount && accounts.includes(selectedAccount)
      ? selectedAccount
      : accounts[0]

  const accountPositions = useMemo(() => {
    if (!activeAccount) {
      return portfolio?.positions ?? []
    }

    return (
      portfolio?.positions.filter(
        (position) => position.account === activeAccount,
      ) ?? []
    )
  }, [portfolio, activeAccount])

  const activeAccountSummary = useMemo(() => {
    return (
      portfolio?.accounts.find((account) => account.account === activeAccount) ??
      null
    )
  }, [portfolio, activeAccount])

  return {
    accounts,
    activeAccount,
    accountPositions,
    activeAccountSummary,
  }
}
