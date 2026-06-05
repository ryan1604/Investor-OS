import { useEffect } from 'react'

import type { IChartApi, LogicalRange } from 'lightweight-charts'

export function useSyncedChartRange(
  priceChart: IChartApi | null,
  rsiChart: IChartApi | null,
) {
  useEffect(() => {
    if (!priceChart || !rsiChart) {
      return
    }

    let isSyncing = false
    const syncRange = (targetChart: IChartApi, range: LogicalRange | null) => {
      if (isSyncing || !range) {
        return
      }

      isSyncing = true
      targetChart.timeScale().setVisibleLogicalRange(range)
      isSyncing = false
    }
    const syncRsiToPrice = (range: LogicalRange | null) => {
      syncRange(rsiChart, range)
    }
    const syncPriceToRsi = (range: LogicalRange | null) => {
      syncRange(priceChart, range)
    }

    priceChart.timeScale().subscribeVisibleLogicalRangeChange(syncRsiToPrice)
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange(syncPriceToRsi)

    const currentPriceRange = priceChart.timeScale().getVisibleLogicalRange()
    if (currentPriceRange) {
      rsiChart.timeScale().setVisibleLogicalRange(currentPriceRange)
    }

    return () => {
      priceChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncRsiToPrice)
      rsiChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncPriceToRsi)
    }
  }, [priceChart, rsiChart])
}
