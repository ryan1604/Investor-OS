import { useCallback } from 'react'

import {
  VirtualizedResultsTable,
  type ResultsTableColumn,
} from '@/features/options-screeners/components/VirtualizedResultsTable'
import {
  formatScreenerDelta,
  formatScreenerPercentage,
  formatScreenerPrice,
  type CreditSpreadCandidate,
} from '@/features/options-screeners/lib/screenerResults'
import type { CsSortKey } from '@/features/options-screeners/OptionsScreenersProvider'

type Column = ResultsTableColumn<CreditSpreadCandidate, CsSortKey>

const tableGrid =
  'grid-cols-[minmax(90px,0.8fr)_minmax(150px,1.2fr)_minmax(170px,1.4fr)_minmax(120px,1fr)_minmax(110px,0.9fr)_minmax(110px,0.9fr)_minmax(130px,1.1fr)_minmax(70px,0.7fr)_minmax(90px,0.8fr)_minmax(90px,0.8fr)_minmax(90px,0.8fr)_minmax(110px,1fr)]'

const columns: Column[] = [
  { key: 'ticker', label: 'Ticker', render: (row) => row.ticker },
  {
    key: 'strategy',
    label: 'Strategy',
    render: (row) =>
      row.strategy === 'put_credit_spread' ? 'Put credit' : 'Call credit',
  },
  {
    key: 'annualized_return',
    label: 'Annualized Return %',
    render: (row) => formatScreenerPercentage(row.annualized_return),
  },
  {
    key: 'stock_price',
    label: 'Stock Price',
    render: (row) => formatScreenerPrice(row.stock_price),
  },
  {
    key: 'short_strike',
    label: 'Short Strike',
    render: (row) => formatScreenerPrice(row.short_strike),
  },
  {
    key: 'long_strike',
    label: 'Long Strike',
    render: (row) => formatScreenerPrice(row.long_strike),
  },
  { key: 'expiration', label: 'Expiration', render: (row) => row.expiration },
  { key: 'dte', label: 'DTE', render: (row) => String(row.dte) },
  {
    key: 'short_delta',
    label: 'Delta',
    render: (row) => formatScreenerDelta(row.short_delta),
  },
  {
    key: 'net_bid',
    label: 'Net Bid',
    render: (row) => formatScreenerPrice(row.net_bid),
  },
  {
    key: 'net_ask',
    label: 'Net Ask',
    render: (row) => formatScreenerPrice(row.net_ask),
  },
  {
    key: 'distance_percentage',
    label: 'Distance %',
    render: (row) => formatScreenerPercentage(row.distance_percentage),
  },
]

export function CsResultsTable({
  candidates,
  emptyMessage = 'No matching spreads',
  onActivate,
  sort,
  onSort,
}: {
  candidates: CreditSpreadCandidate[]
  emptyMessage?: string
  onActivate?: (candidate: CreditSpreadCandidate) => void
  sort: { key: CsSortKey; direction: 'asc' | 'desc' }
  onSort: (key: CsSortKey) => void
}) {
  const rowValue = useCallback(
    (candidate: CreditSpreadCandidate, key: CsSortKey) => candidate[key],
    [],
  )

  return (
    <VirtualizedResultsTable
      candidates={candidates}
      columns={columns}
      emptyMessage={emptyMessage}
      gridClassName={tableGrid}
      minWidthClassName="min-w-[1360px]"
      rowKey={candidateKey}
      rowValue={rowValue}
      sort={sort}
      onSort={onSort}
      onActivate={onActivate}
    />
  )
}

function candidateKey(candidate: CreditSpreadCandidate) {
  return [
    candidate.ticker,
    candidate.strategy,
    candidate.expiration,
    candidate.short_strike,
    candidate.long_strike,
    contractKey(candidate.short_contract),
    contractKey(candidate.long_contract),
  ].join('|')
}

function contractKey(contract: CreditSpreadCandidate['short_contract']) {
  return contract.con_id ?? contract.local_symbol ?? 'unresolved'
}
