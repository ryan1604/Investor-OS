import { useMemo } from 'react'

import {
  VirtualizedResultsTable,
  type ResultsTableColumn,
} from '@/features/options-screeners/components/VirtualizedResultsTable'
import {
  formatScreenerDelta,
  formatScreenerPercentage,
  formatScreenerPrice,
  type CashSecuredPutCandidate,
  type CoveredCallCandidate,
} from '@/features/options-screeners/lib/screenerResults'

export type SingleLegSortKey =
  | 'ticker'
  | 'annualized_return'
  | 'stock_price'
  | 'strike'
  | 'expiration'
  | 'dte'
  | 'delta'
  | 'bid'
  | 'ask'
  | 'discount_percentage'
  | 'gain_percentage'

export type SingleLegCandidate = CashSecuredPutCandidate | CoveredCallCandidate

export type SingleLegColumn<Candidate extends SingleLegCandidate> =
  ResultsTableColumn<Candidate, SingleLegSortKey>

const tableGrid =
  'grid-cols-[minmax(100px,1fr)_minmax(180px,1.5fr)_minmax(120px,1fr)_minmax(100px,0.9fr)_minmax(130px,1.1fr)_minmax(70px,0.7fr)_minmax(90px,0.8fr)_minmax(90px,0.8fr)_minmax(90px,0.8fr)_minmax(110px,1fr)]'

const sharedColumns: SingleLegColumn<SingleLegCandidate>[] = [
  { key: 'ticker', label: 'Ticker', render: (row) => row.ticker },
  {
    key: 'annualized_return',
    label: 'Annualized Return %',
    render: (row) => formatOptional(row.annualized_return, formatScreenerPercentage),
  },
  {
    key: 'stock_price',
    label: 'Stock Price',
    render: (row) => formatOptional(row.stock_price, formatScreenerPrice),
  },
  {
    key: 'strike',
    label: 'Strike',
    render: (row) => formatOptional(row.strike, formatScreenerPrice),
  },
  { key: 'expiration', label: 'Expiration', render: (row) => row.expiration || '-' },
  {
    key: 'dte',
    label: 'DTE',
    render: (row) => formatOptional(row.dte, String),
  },
  {
    key: 'delta',
    label: 'Delta',
    render: (row) => formatOptional(row.delta, formatScreenerDelta),
  },
  {
    key: 'bid',
    label: 'Bid',
    render: (row) => formatOptional(row.bid, formatScreenerPrice),
  },
  {
    key: 'ask',
    label: 'Ask',
    render: (row) => formatOptional(row.ask, formatScreenerPrice),
  },
]

export function SingleLegResultsTable<Candidate extends SingleLegCandidate>({
  candidates,
  emptyMessage = 'No matching contracts',
  finalColumn,
  onActivate,
  sort,
  onSort,
}: {
  candidates: Candidate[]
  emptyMessage?: string
  finalColumn: SingleLegColumn<Candidate>
  onActivate?: (candidate: Candidate) => void
  sort: { key: SingleLegSortKey; direction: 'asc' | 'desc' }
  onSort: (key: SingleLegSortKey) => void
}) {
  const columns = useMemo(
    () => [...(sharedColumns as SingleLegColumn<Candidate>[]), finalColumn],
    [finalColumn],
  )

  return (
    <VirtualizedResultsTable
      candidates={candidates}
      columns={columns}
      emptyMessage={emptyMessage}
      gridClassName={tableGrid}
      minWidthClassName="min-w-[1120px]"
      rowKey={candidateKey}
      rowValue={candidateValue}
      sort={sort}
      onSort={onSort}
      onActivate={onActivate}
    />
  )
}

function candidateKey(candidate: SingleLegCandidate) {
  return (
    candidate.contract.con_id ??
    `${candidate.ticker}-${candidate.expiration}-${candidate.strike}`
  )
}

function candidateValue(
  candidate: SingleLegCandidate,
  key: SingleLegSortKey,
) {
  if (key === 'discount_percentage') {
    return 'discount_percentage' in candidate ? candidate.discount_percentage : 0
  }
  if (key === 'gain_percentage') {
    return 'gain_percentage' in candidate ? candidate.gain_percentage : 0
  }
  return candidate[key]
}

function formatOptional(
  value: number | null | undefined,
  formatter: (value: number) => string,
) {
  return value == null ? '-' : formatter(value)
}
