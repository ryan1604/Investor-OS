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
import { OrdersPage } from '@/features/orders/OrdersPage'
import { useOrders } from '@/features/orders/hooks/useOrders'
import { PortfolioPage } from '@/features/portfolio/PortfolioPage'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'
import { RankStocksPage } from '@/features/rank-stocks/RankStocksPage'
import { StockAnalysisPage } from '@/features/stock-analysis/StockAnalysisPage'

export type AppPage =
  | 'portfolio'
  | 'options'
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

function OrdersRoute() {
  const orders = useOrders()

  return <OrdersPage orders={orders} />
}

export default App
