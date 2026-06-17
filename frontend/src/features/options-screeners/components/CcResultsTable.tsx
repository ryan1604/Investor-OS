import {
  SingleLegResultsTable,
  type SingleLegColumn,
  type SingleLegSortKey,
} from '@/features/options-screeners/components/SingleLegResultsTable'
import {
  formatScreenerPercentage,
  type CoveredCallCandidate,
} from '@/features/options-screeners/lib/screenerResults'
import type { CcSortKey } from '@/features/options-screeners/OptionsScreenersProvider'

const gainColumn: SingleLegColumn<CoveredCallCandidate> = {
  key: 'gain_percentage' as const,
  label: 'Gain %',
  render: (row) => formatScreenerPercentage(row.gain_percentage),
}

export function CcResultsTable({
  candidates,
  emptyMessage,
  onActivate,
  sort,
  onSort,
}: {
  candidates: CoveredCallCandidate[]
  emptyMessage?: string
  onActivate?: (candidate: CoveredCallCandidate) => void
  sort: { key: CcSortKey; direction: 'asc' | 'desc' }
  onSort: (key: CcSortKey) => void
}) {
  return (
    <SingleLegResultsTable
      candidates={candidates}
      emptyMessage={emptyMessage}
      finalColumn={gainColumn}
      sort={sort}
      onSort={(key: SingleLegSortKey) => {
        if (key !== 'discount_percentage') {
          onSort(key)
        }
      }}
      onActivate={onActivate}
    />
  )
}
