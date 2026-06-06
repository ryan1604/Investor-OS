import { lazy, Suspense, useState } from 'react'

import { AppSidebar } from '@/components/AppSidebar'
import {
  SidebarInset,
  SidebarProvider,
} from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useOrders } from '@/features/orders/hooks/useOrders'
import { PortfolioPage } from '@/features/portfolio/PortfolioPage'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'

export type AppPage =
  | 'portfolio'
  | 'options'
  | 'orders'
  | 'stock-analysis'
  | 'rank-stocks'

const OptionsPage = lazy(() =>
  import('@/features/options/OptionsPage').then((module) => ({
    default: module.OptionsPage,
  })),
)
const OrdersPage = lazy(() =>
  import('@/features/orders/OrdersPage').then((module) => ({
    default: module.OrdersPage,
  })),
)
const StockAnalysisPage = lazy(() =>
  import('@/features/stock-analysis/StockAnalysisPage').then((module) => ({
    default: module.StockAnalysisPage,
  })),
)
const RankStocksPage = lazy(() =>
  import('@/features/rank-stocks/RankStocksPage').then((module) => ({
    default: module.RankStocksPage,
  })),
)

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
            <Suspense fallback={<PageLoading />}>
              <OptionsRoute
                selectedAccount={selectedPortfolioAccount}
              />
            </Suspense>
          ) : activePage === 'orders' ? (
            <Suspense fallback={<PageLoading />}>
              <OrdersRoute />
            </Suspense>
          ) : activePage === 'stock-analysis' ? (
            <Suspense fallback={<PageLoading />}>
              <StockAnalysisPage />
            </Suspense>
          ) : (
            <Suspense fallback={<PageLoading />}>
              <RankStocksPage />
            </Suspense>
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

function PageLoading() {
  return (
    <div className="text-sm text-muted-foreground" role="status">
      Loading page...
    </div>
  )
}

export default App
