import { useState } from 'react'

import { AppSidebar } from '@/components/AppSidebar'
import {
  SidebarInset,
  SidebarProvider,
} from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
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
  | 'rank-stocks'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('portfolio')
  const [selectedPortfolioAccount, setSelectedPortfolioAccount] = useState<
    string | null
  >(null)

  return (
    <TooltipProvider>
      <OptionsScreenersProvider>
        <SidebarProvider className="min-h-full">
          <AppSidebar activePage={activePage} onPageChange={setActivePage} />

          <SidebarInset className="min-w-0 p-6">
            {activePage === 'portfolio' ? (
              <PortfolioRoute
                selectedAccount={selectedPortfolioAccount}
                onSelectedAccountChange={setSelectedPortfolioAccount}
              />
            ) : activePage === 'options' ? (
              <OptionsRoute selectedAccount={selectedPortfolioAccount} />
            ) : activePage === 'csp-screener' ? (
              <CspScreenerRoute selectedAccount={selectedPortfolioAccount} />
            ) : activePage === 'cc-screener' ? (
              <CcScreenerRoute selectedAccount={selectedPortfolioAccount} />
            ) : activePage === 'cs-screener' ? (
              <CsScreenerRoute selectedAccount={selectedPortfolioAccount} />
            ) : activePage === 'orders' ? (
              <OrdersRoute />
            ) : activePage === 'options-trade-tracker' ? (
              <OptionsTradeTrackerPage />
            ) : activePage === 'stock-analysis' ? (
              <StockAnalysisPage />
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

function PortfolioRoute({
  selectedAccount,
  onSelectedAccountChange,
}: {
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}) {
  const portfolioState = usePortfolio()

  return (
    <PortfolioPage
      portfolioState={portfolioState}
      selectedAccount={selectedAccount}
      onSelectedAccountChange={onSelectedAccountChange}
    />
  )
}

function OptionsRoute({ selectedAccount }: { selectedAccount: string | null }) {
  const orders = useOrders()
  const portfolioState = usePortfolio()

  return (
    <OptionsPage
      orders={orders}
      portfolio={portfolioState.portfolio}
      selectedAccount={selectedAccount}
    />
  )
}

function CspScreenerRoute({
  selectedAccount,
}: {
  selectedAccount: string | null
}) {
  const portfolioState = usePortfolio()

  return (
    <CspScreenerPage
      portfolio={portfolioState.portfolio}
      selectedAccount={selectedAccount}
    />
  )
}

function CcScreenerRoute({
  selectedAccount,
}: {
  selectedAccount: string | null
}) {
  const portfolioState = usePortfolio()

  return (
    <CcScreenerPage
      portfolio={portfolioState.portfolio}
      selectedAccount={selectedAccount}
    />
  )
}

function CsScreenerRoute({
  selectedAccount,
}: {
  selectedAccount: string | null
}) {
  const portfolioState = usePortfolio()

  return (
    <CsScreenerPage
      portfolio={portfolioState.portfolio}
      selectedAccount={selectedAccount}
    />
  )
}

function OrdersRoute() {
  const orders = useOrders()

  return <OrdersPage orders={orders} />
}

export default App
