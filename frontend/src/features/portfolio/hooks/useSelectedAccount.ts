import { useMemo } from 'react'

import type { PortfolioResponse } from '@/api/portfolio'

export function portfolioAccountIds(portfolio: PortfolioResponse | null) {
  return Array.from(
    new Set([
      ...(portfolio?.accounts.map((account) => account.account) ?? []),
      ...(portfolio?.positions.map((position) => position.account) ?? []),
    ]),
  ).sort()
}

export function useSelectedAccount(
  portfolio: PortfolioResponse | null,
  selectedAccount: string | null,
  savedAccounts: string[] = [],
) {
  const accounts = useMemo(() => {
    const liveAccounts = Array.from(new Set([...portfolioAccountIds(portfolio), ...savedAccounts])).sort()
    if (!portfolio?.status.connected && selectedAccount) {
      return Array.from(new Set([...liveAccounts, selectedAccount])).sort()
    }
    return liveAccounts
  }, [portfolio, selectedAccount, savedAccounts])

  const activeAccount = accounts.includes(selectedAccount ?? '')
    ? selectedAccount ?? undefined
    : accounts[0]

  const accountPositions = useMemo(() => {
    if (!activeAccount) {
      return []
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
