import { useMemo, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'

import { Button } from '@/components/ui/button'

export type ResultsTableColumn<Candidate, SortKey extends string> = {
  key: SortKey
  label: string
  render: (candidate: Candidate) => string
}

export function VirtualizedResultsTable<Candidate, SortKey extends string>({
  candidates,
  columns,
  emptyMessage,
  gridClassName,
  minWidthClassName,
  rowKey,
  rowValue,
  onActivate,
  sort,
  onSort,
}: {
  candidates: Candidate[]
  columns: ResultsTableColumn<Candidate, SortKey>[]
  emptyMessage: string
  gridClassName: string
  minWidthClassName: string
  rowKey: (candidate: Candidate) => string | number
  rowValue: (candidate: Candidate, key: SortKey) => string | number | null
  onActivate?: (candidate: Candidate) => void
  sort: { key: SortKey; direction: 'asc' | 'desc' }
  onSort: (key: SortKey) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const sorted = useMemo(
    () => sortCandidates(candidates, sort.key, sort.direction, rowValue),
    [candidates, rowValue, sort],
  )
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual intentionally returns mutable helpers.
  const virtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 43,
    overscan: 8,
    initialRect: { width: 1360, height: 420 },
  })

  return (
    <div
      ref={scrollRef}
      className="h-[min(52vh,34rem)] min-h-72 overflow-auto rounded-lg border"
    >
      <div className={`${minWidthClassName} text-xs`} role="table">
        <div
          className={`sticky top-0 z-10 grid ${gridClassName} border-b bg-background/95 backdrop-blur`}
          role="row"
        >
          {columns.map((column) => (
            <div key={column.key} role="columnheader">
              <Button
                variant="ghost"
                size="sm"
                className="h-10 w-full cursor-pointer justify-start gap-1 px-3 text-xs"
                onClick={() => onSort(column.key)}
              >
                {column.label}
                <SortIcon column={column.key} sort={sort} />
              </Button>
            </div>
          ))}
        </div>
        {sorted.length ? (
          <div
            role="rowgroup"
            className="relative"
            style={{ height: virtualizer.getTotalSize() }}
          >
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const candidate = sorted[virtualRow.index]
              return (
                <div
                  key={rowKey(candidate)}
                  role="row"
                  tabIndex={0}
                  className={`absolute left-0 top-0 grid w-full cursor-pointer ${gridClassName} border-b bg-background transition-colors hover:bg-accent/70 focus-visible:z-10 focus-visible:bg-accent focus-visible:outline-2 focus-visible:outline-ring`}
                  style={{
                    height: virtualRow.size,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  onClick={() => activate(candidate, onActivate)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      activate(candidate, onActivate)
                    }
                  }}
                >
                  {columns.map((column) => (
                    <div
                      key={column.key}
                      role="cell"
                      className={`truncate px-3 py-2.5 text-left tabular-nums ${
                        column.key === 'ticker' ? 'font-mono font-semibold' : ''
                      }`}
                    >
                      {column.render(candidate)}
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="grid h-40 place-items-center text-muted-foreground">
            {emptyMessage}
          </div>
        )}
      </div>
    </div>
  )
}

function SortIcon<SortKey extends string>({
  column,
  sort,
}: {
  column: SortKey
  sort: { key: SortKey; direction: 'asc' | 'desc' }
}) {
  if (sort.key !== column) {
    return <ChevronsUpDown className="size-3 opacity-35" />
  }
  return sort.direction === 'asc' ? (
    <ArrowUp className="size-3" />
  ) : (
    <ArrowDown className="size-3" />
  )
}

function sortCandidates<Candidate, SortKey extends string>(
  candidates: Candidate[],
  key: SortKey,
  direction: 'asc' | 'desc',
  rowValue: (candidate: Candidate, key: SortKey) => string | number | null,
) {
  const multiplier = direction === 'asc' ? 1 : -1
  return [...candidates].sort((first, second) => {
    const firstValue = rowValue(first, key)
    const secondValue = rowValue(second, key)
    const compared =
      typeof firstValue === 'string' && typeof secondValue === 'string'
        ? firstValue.localeCompare(secondValue)
        : Number(firstValue ?? 0) - Number(secondValue ?? 0)
    return compared * multiplier
  })
}

function activate<Candidate>(
  candidate: Candidate,
  onActivate?: (candidate: Candidate) => void,
) {
  if (window.getSelection()?.toString()) {
    return
  }
  onActivate?.(candidate)
}
