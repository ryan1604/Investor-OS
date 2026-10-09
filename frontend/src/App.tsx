import { useEffect, useMemo, useState, type ReactNode } from 'react'

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
import { PortfolioAnalysisPage } from '@/features/portfolio-analysis/PortfolioAnalysisPage'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'
import { portfolioAccountIds } from '@/features/portfolio/hooks/useSelectedAccount'
import { RankStocksPage } from '@/features/rank-stocks/RankStocksPage'
import { StockAnalysisPage } from '@/features/stock-analysis/StockAnalysisPage'
import type { AppPage } from '@/lib/pages'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('portfolio')
  const [hasVisitedOptions, setHasVisitedOptions] = useState(false)
  const [selectedAccount, setSelectedAccount] = useState<
    string | null
  >(null)
  const portfolioState = usePortfolio()
  const ordersState = useOrders(hasVisitedOptions || activePage === 'orders')
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

  const pageViews: Record<AppPage, ReactNode> = {
    options: null,
    portfolio: (
      <PortfolioPage
        portfolioState={portfolioState}
        selectedAccount={selectedAccount}
        onSelectedAccountChange={setSelectedAccount}
      />
    ),
    'portfolio-analysis': (
      <PortfolioAnalysisPage
        accounts={accounts}
        selectedAccount={tradingAccount}
        onSelectedAccountChange={setSelectedAccount}
      />
    ),
    'csp-screener': (
      <CspScreenerPage
        portfolio={portfolioState.portfolio}
        selectedAccount={tradingAccount}
      />
    ),
    'cc-screener': (
      <CcScreenerPage
        portfolio={portfolioState.portfolio}
        selectedAccount={tradingAccount}
      />
    ),
    'cs-screener': (
      <CsScreenerPage
        portfolio={portfolioState.portfolio}
        selectedAccount={tradingAccount}
      />
    ),
    orders: (
      <OrdersRoute
        accounts={accounts}
        ordersState={ordersState}
        selectedAccount={tradingAccount}
        onSelectedAccountChange={setSelectedAccount}
      />
    ),
    'options-trade-tracker': <OptionsTradeTrackerPage />,
    'day-trading-tracker': <DayTradingTrackerPage />,
    'stock-analysis': <StockAnalysisPage />,
    'earnings-watch': <EarningsWatchPage />,
    'rank-stocks': <RankStocksPage />,
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
                ordersState={ordersState}
                selectedAccount={tradingAccount}
                onSelectedAccountChange={setSelectedAccount}
              />
            </div>
          ) : null}

          {pageViews[activePage]}
        </main>
        <Toaster />
      </div>
    </OptionsScreenersProvider>
  )
}

function OptionsRoute({
  accounts,
  ordersState,
  isActive,
  portfolioState,
  selectedAccount,
  onSelectedAccountChange,
}: {
  accounts: string[]
  ordersState: ReturnType<typeof useOrders>
  isActive: boolean
  portfolioState: ReturnType<typeof usePortfolio>
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}) {
  const { orders } = ordersState

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
  ordersState,
  selectedAccount,
  onSelectedAccountChange,
}: {
  accounts: string[]
  ordersState: ReturnType<typeof useOrders>
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}) {
  const { orders, warning } = ordersState

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
