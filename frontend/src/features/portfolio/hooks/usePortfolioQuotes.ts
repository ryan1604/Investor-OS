import { useEffect } from 'react'

import { PORTFOLIO_QUOTES_WS_URL } from '@/api/portfolio'
import { connectWithBackoff } from '@/lib/connectWithBackoff'

// Holds IB position quotes open only while the Portfolio page is mounted,
// so their market-data lines are free for other pages otherwise.
export function usePortfolioQuotes() {
  useEffect(() => connectWithBackoff(PORTFOLIO_QUOTES_WS_URL), [])
}
