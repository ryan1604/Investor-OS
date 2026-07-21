import { useEffect, useMemo, useState } from 'react'

import { AppSidebar } from '@/components/AppSidebar'
import {
  SidebarInset,
  SidebarProvider,
} from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
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
  | 'orders'
  | 'stock-analysis'
  | 'earnings-watch'
  | 'rank-stocks'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('portfolio')
  const [selectedAccount, setSelectedAccount] = useState<
    string | null
  >(null)
  const portfolioState = usePortfolio()
  const accounts = useMemo(
    () => portfolioAccountIds(portfolioState.portfolio),
    [portfolioState.portfolio],
  )

  useEffect(() => {
    // Keep the session-only selected account valid as portfolio accounts load.
    if (!accounts.length) {
      if (selectedAccount !== null) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSelectedAccount(null)
      }
      return
    }

    if (!selectedAccount || !accounts.includes(selectedAccount)) {
      setSelectedAccount(accounts[0])
    }
  }, [accounts, selectedAccount])

  return (
    <TooltipProvider>
      <OptionsScreenersProvider>
        <SidebarProvider className="min-h-full">
          <AppSidebar activePage={activePage} onPageChange={setActivePage} />

          <SidebarInset className="min-w-0 p-6">
            {activePage === 'portfolio' ? (
              <PortfolioPage
                portfolioState={portfolioState}
                selectedAccount={selectedAccount}
                onSelectedAccountChange={setSelectedAccount}
              />
            ) : activePage === 'options' ? (
              <OptionsRoute
                accounts={accounts}
                portfolioState={portfolioState}
                selectedAccount={selectedAccount}
                onSelectedAccountChange={setSelectedAccount}
              />
            ) : activePage === 'csp-screener' ? (
              <CspScreenerPage
                portfolio={portfolioState.portfolio}
                selectedAccount={selectedAccount}
              />
            ) : activePage === 'cc-screener' ? (
              <CcScreenerPage
                portfolio={portfolioState.portfolio}
                selectedAccount={selectedAccount}
              />
            ) : activePage === 'cs-screener' ? (
              <CsScreenerPage
                portfolio={portfolioState.portfolio}
                selectedAccount={selectedAccount}
              />
            ) : activePage === 'orders' ? (
              <OrdersRoute
                accounts={accounts}
                selectedAccount={selectedAccount}
                onSelectedAccountChange={setSelectedAccount}
              />
            ) : activePage === 'options-trade-tracker' ? (
              <OptionsTradeTrackerPage />
            ) : activePage === 'stock-analysis' ? (
              <StockAnalysisPage />
            ) : activePage === 'earnings-watch' ? (
              <EarningsWatchPage />
            ) : (
              <RankStocksPage />
            )}
          </SidebarInset>
          <Toaster />
        </SidebarProvider>
      </OptionsScreenersProvider>
    </TooltipProvider>
  )
}

function OptionsRoute({
  accounts,
  portfolioState,
  selectedAccount,
  onSelectedAccountChange,
}: {
  accounts: string[]
  portfolioState: ReturnType<typeof usePortfolio>
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}) {
  const { orders } = useOrders()

  return (
    <OptionsPage
      accounts={accounts}
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
