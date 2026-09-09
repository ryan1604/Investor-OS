import { useEffect, useMemo, useState } from 'react'

import { AppSidebar } from '@/components/AppSidebar'
import { Toaster } from '@/components/ui/sonner'
import { DayTradingTrackerPage } from '@/features/day-trading-tracker/DayTradingTrackerPage'
import { EarningsWatchPage } from '@/features/earnings-watch/EarningsWatchPage'
import { OptionsTradeTrackerPage } from '@/features/options-trade-tracker/OptionsTradeTrackerPage'
import { OptionsPage } from '@/features/options/OptionsPage'
import { CspScreenerPage } from '@/features/options-screeners/CspScreenerPage'
import { CcScreenerPage } from '@/features/options-screeners/CcScreenerPage'
import { CsScreenerPage } from '@/features/options-screeners/CsScreenerPage'
import { OptionsScreenersProvider } from '@/features/options-screeners/OptionsScreenersProvider'
import { OrdersPage } from '@/features/orders/OrdersPage'
import { useOrders } from '@/features/orders/hooks/useOrders'
import { PortfolioPage } from '@/features/portfolio/PortfolioPage'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'
import { portfolioAccountIds } from '@/features/portfolio/hooks/useSelectedAccount'
import { RankStocksPage } from '@/features/rank-stocks/RankStocksPage'
import { StockAnalysisPage } from '@/features/stock-analysis/StockAnalysisPage'

export type AppPage =
  | 'portfolio'
  | 'options'
  | 'csp-screener'
  | 'cc-screener'
  | 'cs-screener'
  | 'options-trade-tracker'
  | 'day-trading-tracker'
  | 'orders'
  | 'stock-analysis'
  | 'earnings-watch'
  | 'rank-stocks'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('portfolio')
  const [hasVisitedOptions, setHasVisitedOptions] = useState(false)
  const [selectedAccount, setSelectedAccount] = useState<
    string | null
  >(null)
  const portfolioState = usePortfolio()
  const accounts = useMemo(
    () => portfolioAccountIds(portfolioState.portfolio),
    [portfolioState.portfolio],
  )

  useEffect(() => {
    // Initialize selection without discarding saved-only Portfolio accounts.
    if (!accounts.length) {
      return
    }

    if (!selectedAccount) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedAccount(accounts[0])
    }
  }, [accounts, selectedAccount])

  const tradingAccount = selectedAccount && accounts.includes(selectedAccount)
    ? selectedAccount
    : accounts[0] ?? null

  const handlePageChange = (page: AppPage) => {
    if (page === 'options') {
      setHasVisitedOptions(true)
    }
    setActivePage(page)
  }

  return (
    <OptionsScreenersProvider>
      <div className="flex min-h-svh w-full items-stretch">
        <AppSidebar activePage={activePage} onPageChange={handlePageChange} />

        <main className="relative flex min-w-0 w-full flex-1 flex-col bg-background p-6">
          {hasVisitedOptions ? (
            <div
              className={activePage === 'options' ? 'contents' : undefined}
              data-testid="options-workspace"
              hidden={activePage !== 'options'}
            >
              <OptionsRoute
                accounts={accounts}
                isActive={activePage === 'options'}
                portfolioState={portfolioState}
                selectedAccount={tradingAccount}
                onSelectedAccountChange={setSelectedAccount}
              />
            </div>
          ) : null}

          {activePage === 'options' ? null : activePage === 'portfolio' ? (
            <PortfolioPage
              portfolioState={portfolioState}
              selectedAccount={selectedAccount}
              onSelectedAccountChange={setSelectedAccount}
            />
          ) : activePage === 'csp-screener' ? (
            <CspScreenerPage
              portfolio={portfolioState.portfolio}
              selectedAccount={tradingAccount}
            />
          ) : activePage === 'cc-screener' ? (
            <CcScreenerPage
              portfolio={portfolioState.portfolio}
              selectedAccount={tradingAccount}
            />
          ) : activePage === 'cs-screener' ? (
            <CsScreenerPage
              portfolio={portfolioState.portfolio}
              selectedAccount={tradingAccount}
            />
          ) : activePage === 'orders' ? (
            <OrdersRoute
              accounts={accounts}
              selectedAccount={tradingAccount}
              onSelectedAccountChange={setSelectedAccount}
            />
          ) : activePage === 'options-trade-tracker' ? (
            <OptionsTradeTrackerPage />
          ) : activePage === 'day-trading-tracker' ? (
            <DayTradingTrackerPage />
          ) : activePage === 'stock-analysis' ? (
            <StockAnalysisPage />
          ) : activePage === 'earnings-watch' ? (
            <EarningsWatchPage />
          ) : (
            <RankStocksPage />
          )}
        </main>
        <Toaster />
      </div>
    </OptionsScreenersProvider>
  )
}

function OptionsRoute({
  accounts,
  isActive,
  portfolioState,
  selectedAccount,
  onSelectedAccountChange,
}: {
  accounts: string[]
  isActive: boolean
  portfolioState: ReturnType<typeof usePortfolio>
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}) {
  const { orders } = useOrders()

  return (
    <OptionsPage
      accounts={accounts}
      isActive={isActive}
      orders={orders}
      portfolio={portfolioState.portfolio}
      selectedAccount={selectedAccount}
      onSelectedAccountChange={onSelectedAccountChange}
    />
  )
}

function OrdersRoute({
  accounts,
  selectedAccount,
  onSelectedAccountChange,
}: {
  accounts: string[]
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}) {
  const { orders, warning } = useOrders()

  return (
    <OrdersPage
      accounts={accounts}
      orders={orders}
      warning={warning}
      selectedAccount={selectedAccount}
      onSelectedAccountChange={onSelectedAccountChange}
    />
  )
}

export default App
