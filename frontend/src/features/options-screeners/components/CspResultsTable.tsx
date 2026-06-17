import {
  SingleLegResultsTable,
  type SingleLegColumn,
  type SingleLegSortKey,
} from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  formatScreenerPercentage,
  type CashSecuredPutCandidate,
} from '@/features/options-screeners/lib/screenerResults'
import type { CspSortKey } from '@/features/options-screeners/OptionsScreenersProvider'

const discountColumn: SingleLegColumn<CashSecuredPutCandidate> = {
  key: 'discount_percentage' as const,
  label: 'Discount %',
  render: (row) => formatScreenerPercentage(row.discount_percentage),
}

export function CspResultsTable({
  candidates,
  emptyMessage,
  onActivate,
  sort,
  onSort,
}: {
  candidates: CashSecuredPutCandidate[]
  emptyMessage?: string
  onActivate?: (candidate: CashSecuredPutCandidate) => void
  sort: { key: CspSortKey; direction: 'asc' | 'desc' }
  onSort: (key: CspSortKey) => void
}) {
  return (
    <SingleLegResultsTable
      candidates={candidates}
      emptyMessage={emptyMessage}
      finalColumn={discountColumn}
      sort={sort}
      onSort={(key: SingleLegSortKey) => {
        if (key !== 'gain_percentage') {
          onSort(key)
        }
      }}
      onActivate={onActivate}
    />
  )
}
