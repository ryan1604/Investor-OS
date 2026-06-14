import {
  BriefcaseBusiness,
  ChartCandlestick,
  ChartNoAxesCombined,
  ClipboardList,
  ListOrdered,
  ListChecks,
} from 'lucide-react'

import type { AppPage } from '@/App'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

type AppSidebarProps = {
  activePage: AppPage
  onPageChange: (page: AppPage) => void
}

const navigationItems: {
  page: AppPage
  label: string
  icon: typeof BriefcaseBusiness
}[] = [
  {
    page: 'portfolio',
    label: 'Portfolio',
    icon: BriefcaseBusiness,
  },
  {
    page: 'options',
    label: 'Options',
    icon: ChartCandlestick,
  },
  {
    page: 'options-trade-tracker',
    label: 'Options Trade Tracker',
    icon: ClipboardList,
  },
  {
    page: 'orders',
    label: 'Orders',
    icon: ListChecks,
  },
  {
    page: 'stock-analysis',
    label: 'Stock Analysis',
    icon: ChartNoAxesCombined,
  },
  {
    page: 'rank-stocks',
    label: 'Rank Stocks',
    icon: ListOrdered,
  },
]

export function AppSidebar({ activePage, onPageChange }: AppSidebarProps) {
  return (
    <Sidebar collapsible="none" className="min-h-svh bg-sidebar">
      <SidebarHeader className="px-4 py-6 text-lg font-semibold">
        Investor OS
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {navigationItems.map((item) => {
                const Icon = item.icon

                return (
                  <SidebarMenuItem key={item.page}>
                    <SidebarMenuButton
                      isActive={activePage === item.page}
                      tooltip={item.label}
                      className="cursor-pointer active:cursor-pointer"
                      onClick={() => onPageChange(item.page)}
                    >
                      <Icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
