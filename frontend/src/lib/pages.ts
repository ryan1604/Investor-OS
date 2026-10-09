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

export const pages = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    icon: BriefcaseBusiness,
  },
  {
    id: 'portfolio-analysis',
    label: 'Portfolio Analysis',
    icon: Gauge,
  },
  {
    id: 'options',
    label: 'Options',
    icon: ChartCandlestick,
  },
  {
    id: 'orders',
    label: 'Orders',
    icon: ListChecks,
  },
  {
    id: 'csp-screener',
    label: 'CSP Screener',
    icon: Radar,
  },
  {
    id: 'cc-screener',
    label: 'CC Screener',
    icon: Radar,
  },
  {
    id: 'cs-screener',
    label: 'CS Screener',
    icon: Radar,
  },
  {
    id: 'options-trade-tracker',
    label: 'Options Trade Tracker',
    icon: ClipboardList,
  },
  {
    id: 'day-trading-tracker',
    label: 'Day Trading Tracker',
    icon: CalendarDays,
  },
  {
    id: 'stock-analysis',
    label: 'Stock Analysis',
    icon: ChartNoAxesCombined,
  },
  {
    id: 'earnings-watch',
    label: 'Earnings Watch',
    icon: CalendarClock,
  },
  {
    id: 'rank-stocks',
    label: 'Rank Stocks',
    icon: ListOrdered,
  },
] as const

export type AppPage = (typeof pages)[number]['id']
