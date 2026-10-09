import { createContext, useContext } from 'react'

import type {
  CreditSpreadScreenerFilters,
  CreditSpreadStrategy,
  CreditSpreadWidth,
  OptionsScreenerCompletedSnapshot,
  OptionsScreenerFilters,
  OptionsScreenerScanJob,
} from '@/api/optionsScreeners'
import type { SingleLegSortKey } from '@/features/options-screeners/components/SingleLegResultsTable'
import type { ScreenerFilterSlice } from '@/features/options-screeners/hooks/useScreenerFilterSlice'
import type {
  CreditSpreadFilterDraft,
  ScreenerFilterDraft,
} from '@/features/options-screeners/lib/screenerSettings'

export type CspSortKey = Exclude<SingleLegSortKey, 'gain_percentage'>
export type CcSortKey = Exclude<SingleLegSortKey, 'discount_percentage'>
export type CsSortKey =
  | 'ticker'
  | 'strategy'
  | 'annualized_return'
  | 'stock_price'
  | 'short_strike'
  | 'long_strike'
  | 'expiration'
  | 'dte'
  | 'short_delta'
  | 'net_bid'
  | 'net_ask'
  | 'distance_percentage'

type ScreenerSlice<Filters, Key extends string, Draft = ScreenerFilterDraft> =
  ScreenerFilterSlice<Filters, Key, Draft> & {
    tickers: string[]
    latestJob: OptionsScreenerScanJob | null
    snapshot: OptionsScreenerCompletedSnapshot | null
    addTickers: (tickers: string[]) => Promise<void>
    removeTicker: (ticker: string) => Promise<void>
    clearTickers: () => Promise<void>
    startScan: () => Promise<void>
  }

type ScreenerSlices = {
  csp: ScreenerSlice<OptionsScreenerFilters, CspSortKey>
  cc: ScreenerSlice<OptionsScreenerFilters, CcSortKey>
  cs: ScreenerSlice<CreditSpreadScreenerFilters, CsSortKey, CreditSpreadFilterDraft> & {
    toggleStrategyType: (strategy: CreditSpreadStrategy) => void
    toggleSpreadWidth: (width: CreditSpreadWidth) => void
  }
}

export type OptionsScreenersContextValue = {
  screeners: ScreenerSlices
  isLoading: boolean
  loadError: string | null
  tickerSaveError: string | null
  isTickerUpdatePending: boolean
  scanActionError: string | null
  activeJob: OptionsScreenerScanJob | null
  cancelActiveScan: () => Promise<void>
}

export const OptionsScreenersContext =
  createContext<OptionsScreenersContextValue | null>(null)

export function useOptionsScreeners() {
  const context = useContext(OptionsScreenersContext)
  if (!context) {
    throw new Error(
      'useOptionsScreeners must be used within OptionsScreenersProvider.',
    )
  }
  return context
}
