import {
  BriefcaseBusiness,
  CalendarClock,
  CalendarDays,
  ChartCandlestick,
  ChartNoAxesCombined,
  ClipboardList,
  Gauge,
  ListOrdered,
  ListChecks,
  Radar,
} from 'lucide-react'

import type { AppPage } from '@/App'

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
    page: 'portfolio-analysis',
    label: 'Portfolio Analysis',
    icon: Gauge,
  },
  {
    page: 'options',
    label: 'Options',
    icon: ChartCandlestick,
  },
  {
    page: 'orders',
    label: 'Orders',
    icon: ListChecks,
  },
  {
    page: 'csp-screener',
    label: 'CSP Screener',
    icon: Radar,
  },
  {
    page: 'cc-screener',
    label: 'CC Screener',
    icon: Radar,
  },
  {
    page: 'cs-screener',
    label: 'CS Screener',
    icon: Radar,
  },
  {
    page: 'options-trade-tracker',
    label: 'Options Trade Tracker',
    icon: ClipboardList,
  },
  {
    page: 'day-trading-tracker',
    label: 'Day Trading Tracker',
    icon: CalendarDays,
  },
  {
    page: 'stock-analysis',
    label: 'Stock Analysis',
    icon: ChartNoAxesCombined,
  },
  {
    page: 'earnings-watch',
    label: 'Earnings Watch',
    icon: CalendarClock,
  },
  {
    page: 'rank-stocks',
    label: 'Rank Stocks',
    icon: ListOrdered,
  },
]

export function AppSidebar({ activePage, onPageChange }: AppSidebarProps) {
  return (
    <aside className="flex min-h-svh w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground">
      <header className="flex flex-col gap-2 px-4 py-6 text-lg font-semibold">
        Investor OS
      </header>
      <nav
        aria-label="Primary"
        className="no-scrollbar flex min-h-0 flex-1 flex-col gap-0 overflow-auto p-2 text-sm"
      >
        <ul className="flex w-full min-w-0 flex-col gap-0">
          {navigationItems.map((item) => {
            const Icon = item.icon

            return (
              <li key={item.page}>
                <button
                  type="button"
                  aria-current={activePage === item.page ? 'page' : undefined}
                  className="flex h-8 w-full cursor-pointer items-center gap-2 overflow-hidden rounded-md p-2 text-left text-sm ring-sidebar-ring outline-hidden hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:cursor-pointer active:bg-sidebar-accent active:text-sidebar-accent-foreground aria-[current=page]:bg-sidebar-accent aria-[current=page]:font-medium aria-[current=page]:text-sidebar-accent-foreground [&_svg]:size-4 [&_svg]:shrink-0 [&>span:last-child]:truncate"
                  onClick={() => onPageChange(item.page)}
                >
                  <Icon />
                  <span>{item.label}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>
    </aside>
  )
}
