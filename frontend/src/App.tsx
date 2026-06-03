import { useState } from 'react'

import { AppSidebar } from '@/components/AppSidebar'
import {
  SidebarInset,
  SidebarProvider,
} from '@/components/ui/sidebar'
import { OptionsPage } from '@/features/options/OptionsPage'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PortfolioPage } from '@/features/portfolio/PortfolioPage'
import { usePortfolio } from '@/features/portfolio/hooks/usePortfolio'

export type AppPage = 'portfolio' | 'options'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('portfolio')
  const [selectedPortfolioAccount, setSelectedPortfolioAccount] = useState<
    string | null
  >(null)
  const portfolioState = usePortfolio()

  return (
    <TooltipProvider>
      <SidebarProvider className="min-h-full">
        <AppSidebar activePage={activePage} onPageChange={setActivePage} />

        <SidebarInset className="min-w-0 p-6">
          {activePage === 'portfolio' ? (
            <PortfolioPage
              portfolioState={portfolioState}
              selectedAccount={selectedPortfolioAccount}
              onSelectedAccountChange={setSelectedPortfolioAccount}
            />
          ) : (
            <OptionsPage />
          )}
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}

export default App
