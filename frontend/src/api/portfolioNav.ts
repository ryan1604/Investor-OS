import { requestJson } from '@/api/client'

export type NavRow = { account: string; report_date: string; nav: string; currency: string; source: 'flex' | 'portfolioanalyst'; updated_at: string }
export type NavHistory = {
  account: string
  rows: NavRow[]
  latest_report_date: string | null
  currencies: string[]
  currency_changed: boolean
  sync: { configured: boolean; last_successful_sync: string | null; error: string | null; state: 'unconfigured' | 'pending' | 'syncing' | 'current' | 'stale' | 'failed' }
}

export function fetchNav(account: string, signal?: AbortSignal) {
  return requestJson<NavHistory>(`/portfolio/nav?${new URLSearchParams({ account })}`, 'NAV history', { signal })
}

export function fetchNavAccounts(signal?: AbortSignal) {
  return requestJson<string[]>('/portfolio/nav/accounts', 'Saved accounts', { signal })
}
