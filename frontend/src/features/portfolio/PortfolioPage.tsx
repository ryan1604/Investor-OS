import { useCallback, useMemo, useState } from 'react'

import { AccountSummaryCard } from '@/features/portfolio/components/AccountSummaryCard'
import { PortfolioChartSection } from '@/features/portfolio/components/PortfolioChartSection'
import { PortfolioHeader } from '@/features/portfolio/components/PortfolioHeader'
import { PositionsTable } from '@/features/portfolio/components/PositionsTable'
import { usePortfolioChartValues } from '@/features/portfolio/hooks/usePortfolioChartValues'
import {
  DEFAULT_SORT,
  comparePositions,
  groupDisplayPositions,
  nextSortDirection,
  type SortKey,
  type SortState,
} from '@/features/portfolio/lib/positions'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'
import { useSelectedAccount } from '@/features/portfolio/hooks/useSelectedAccount'

type PortfolioPageProps = {
  portfolioState: ReturnType<typeof usePortfolio>
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}

export function PortfolioPage({
  portfolioState,
  selectedAccount,
  onSelectedAccountChange,
}: PortfolioPageProps) {
  const { portfolio, isLoading, error, loadPortfolio } = portfolioState
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT)
  const {
    accounts,
    activeAccount,
    accountPositions,
    activeAccountSummary,
  } = useSelectedAccount(portfolio, selectedAccount)
  const chartValues = usePortfolioChartValues(activeAccount)

  const displayRows = useMemo(() => {
    return groupDisplayPositions(accountPositions)
  }, [accountPositions])

  const displayedPositions = useMemo(() => {
    return [...displayRows].sort((first, second) =>
      comparePositions(first, second, sort),
    )
  }, [displayRows, sort])

  const handleSort = useCallback((key: SortKey) => {
    setSort((currentSort) => ({
      key,
      direction: nextSortDirection(key, currentSort),
    }))
  }, [])

  return (
    <>
      <PortfolioHeader
        accounts={accounts}
        activeAccount={activeAccount}
        isLoading={isLoading}
        status={portfolio?.status ?? null}
        onAccountChange={onSelectedAccountChange}
        onRefresh={() => void loadPortfolio()}
      />

      <AccountSummaryCard
        isLoading={isLoading}
        summary={activeAccountSummary}
      />

      <PositionsTable
        error={error}
        isConnected={portfolio?.status.connected ?? false}
        isLoading={isLoading}
        positions={displayedPositions}
        sort={sort}
        onSort={handleSort}
      />

      <PortfolioChartSection
        account={activeAccount}
        currency={activeAccountSummary?.currency ?? 'USD'}
        error={chartValues.error}
        isLoading={chartValues.isLoading}
        isSaving={chartValues.isSaving}
        onSaveRows={chartValues.saveRows}
        rows={chartValues.rows}
      />
    </>
  )
}
