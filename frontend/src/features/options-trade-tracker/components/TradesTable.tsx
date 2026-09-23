import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from 'react'
import { defaultRangeExtractor, useWindowVirtualizer } from '@tanstack/react-virtual'
import { Plus, Save } from 'lucide-react'

import type {
  OptionsTradeMonth,
  OptionsTradeStatus,
} from '@/api/optionsTradeTrackers'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { TradeRow } from '@/features/options-trade-tracker/components/TradeRow'
import {
  calculateTradesFooterTotal,
  formatPnl,
  type CompletedTradeProjection,
  type TradeDraftField,
  type TradeDraftRow,
  type TradeDraftValidationIssue,
} from '@/features/options-trade-tracker/lib/tradeTracker'
import { signedValueClassName } from '@/lib/format'

type TradesTableProps = {
  rows: TradeDraftRow[]
  completedTrades: CompletedTradeProjection[]
  strategies: string[]
  issues: TradeDraftValidationIssue[]
  isSaving: boolean
  onAddRow: () => void
  onDeleteRow: (localId: string) => void
  onOpenStrategyDialog: () => void
  onReorderRow: (draggedLocalId: string, targetLocalId: string) => void
  onSave: () => void
  onUpdateRow: (
    localId: string,
    field: TradeDraftField,
    value: string | OptionsTradeMonth | OptionsTradeStatus,
  ) => void
}

const EMPTY_ISSUES: TradeDraftValidationIssue[] = []

export function TradesTable({
  rows,
  completedTrades,
  strategies,
  issues,
  isSaving,
  onAddRow,
  onDeleteRow,
  onOpenStrategyDialog,
  onReorderRow,
  onSave,
  onUpdateRow,
}: TradesTableProps) {
  const [draggedRowId, setDraggedRowId] = useState<string | null>(null)
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null)
  const [openRowId, setOpenRowId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLTableSectionElement>(null)
  const [headerHeight, setHeaderHeight] = useState(45)
  const [bodyOffset, setBodyOffset] = useState(45)
  const dragSpeed = useRef(0)
  const tabDirection = useRef(0)
  const addedRowPending = useRef(false)
  const focusFrame = useRef(0)
  const pendingFocus = useRef<{ index: number; control: 'first' | 'last' | 'drag' } | null>(null)
  const rowIndexes = useMemo(
    () => new Map(rows.map((row, index) => [row.localId, index])),
    [rows],
  )
  const getItemKey = useCallback((index: number) => rows[index].localId, [rows])
  const rangeExtractor = useCallback(
    (range: Parameters<typeof defaultRangeExtractor>[0]) => {
      const indexes = new Set(defaultRangeExtractor(range))
      // Keep the active controls alive and their neighbours available to native Tab navigation.
      for (const id of [focusedRowId, openRowId, draggedRowId]) {
        const index = id === null ? undefined : rowIndexes.get(id)
        if (index === undefined) continue
        for (
          let next = Math.max(0, index - 1);
          next <= Math.min(rows.length - 1, index + 1);
          next++
        ) {
          indexes.add(next)
        }
      }
      return [...indexes].sort((a, b) => a - b)
    },
    [focusedRowId, openRowId, draggedRowId, rowIndexes, rows.length],
  )
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    getItemKey,
    estimateSize: () => 55,
    measureElement: (element) => element.getBoundingClientRect().height,
    overscan: 3,
    initialRect: { width: 1200, height: 650 },
    scrollMargin: bodyOffset,
    scrollPaddingStart: headerHeight,
    scrollPaddingEnd: 40,
    rangeExtractor,
  })
  const virtualRows = virtualizer.getVirtualItems()

  const focusRow = useCallback(
    (index: number, control: 'first' | 'last' | 'drag' = 'first') => {
      cancelAnimationFrame(focusFrame.current)
      pendingFocus.current = { index, control }
      focusFrame.current = requestAnimationFrame(() => {
        if (!pendingFocus.current || index < 0 || index >= virtualizer.options.count) return
        // Pin the destination before focusing it. Measured validation heights can
        // change the visible range while a distant scroll is settling.
        setFocusedRowId(String(virtualizer.options.getItemKey(index)))
        virtualizer.scrollToIndex(index, { align: 'auto' })
      })
    },
    [virtualizer],
  )

  useLayoutEffect(() => {
    const pending = pendingFocus.current
    if (!pending) return
    const row = scrollRef.current?.querySelector(`[data-index="${pending.index}"]`)
    const controls = row?.querySelectorAll<HTMLElement>('button, input')
    const target = pending.control === 'drag'
      ? row?.querySelector<HTMLElement>('[data-row-action="drag"]')
      : controls?.[pending.control === 'last' ? controls.length - 1 : 0]
    if (target) {
      pendingFocus.current = null
      target.focus()
    }
  })

  useLayoutEffect(() => {
    const header = headerRef.current
    if (!header) return
    const observer = new ResizeObserver(() =>
      setHeaderHeight(header.getBoundingClientRect().height),
    )
    observer.observe(header)
    return () => observer.disconnect()
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps -- Content above the table can move it on any render; the equality guard stops loops.
  useLayoutEffect(() => {
    // Rows are positioned against the page scroll, so track where the table body starts.
    const table = scrollRef.current
    if (!table) return
    const offset = table.getBoundingClientRect().top + window.scrollY + headerHeight
    if (offset !== bodyOffset) setBodyOffset(offset)
  })

  useLayoutEffect(() => {
    if (addedRowPending.current && rows.length) {
      addedRowPending.current = false
      focusRow(rows.length - 1)
    }
  }, [rows.length, focusRow])

  useEffect(() => {
    const firstIssue = issues[0]
    const index = firstIssue && rowIndexes.get(firstIssue.localId)
    if (index !== undefined) virtualizer.scrollToIndex(index, { align: 'auto' })
    // A new validation result should reveal its first row, not pull every edit back to it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [issues])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      tabDirection.current = event.key === 'Tab' ? (event.shiftKey ? -1 : 1) : 0
    }
    const onPointer = () => {
      tabDirection.current = 0
      pendingFocus.current = null
      cancelAnimationFrame(focusFrame.current)
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('pointerdown', onPointer, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('pointerdown', onPointer, true)
      cancelAnimationFrame(focusFrame.current)
    }
  }, [])

  useEffect(() => {
    if (!draggedRowId) return
    let frame: number
    const scroll = () => {
      if (dragSpeed.current) window.scrollBy(0, dragSpeed.current)
      frame = requestAnimationFrame(scroll)
    }
    frame = requestAnimationFrame(scroll)
    return () => {
      cancelAnimationFrame(frame)
      dragSpeed.current = 0
    }
  }, [draggedRowId])

  const handleMenuOpenChange = useCallback((localId: string, open: boolean) => {
    if (open) setFocusedRowId(localId) // Retain the trigger through Radix's close/focus restoration.
    setOpenRowId((current) =>
      open ? localId : current === localId ? null : current,
    )
  }, [])
  const pnlByRowId = useMemo(
    () => new Map(completedTrades.map(({ row, pnl }) => [row.id, pnl])),
    [completedTrades],
  )
  const footerTotal = useMemo(() => {
    const total = calculateTradesFooterTotal(completedTrades)
    return { text: formatPnl(total), className: signedValueClassName(total) }
  }, [completedTrades])
  const issuesByRowId = useMemo(() => {
    const byRow = new Map<string, TradeDraftValidationIssue[]>()
    for (const issue of issues) {
      const rowIssues = byRow.get(issue.localId)
      if (rowIssues) {
        rowIssues.push(issue)
      } else {
        byRow.set(issue.localId, [issue])
      }
    }
    return byRow
  }, [issues])

  const handleDragStart = useCallback(
    (event: DragEvent<HTMLTableRowElement>, localId: string) => {
      setDraggedRowId(localId)
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', localId)
    },
    [],
  )

  const handleDragEnd = useCallback(() => setDraggedRowId(null), [])

  const handleDrop = useCallback(
    (event: DragEvent<HTMLTableRowElement>, targetLocalId: string) => {
      event.preventDefault()
      const draggedLocalId =
        event.dataTransfer.getData('text/plain') || draggedRowId

      if (draggedLocalId && draggedLocalId !== targetLocalId) {
        onReorderRow(draggedLocalId, targetLocalId)
      }

      setDraggedRowId(null)
    },
    [draggedRowId, onReorderRow],
  )

  return (
    <section className="min-w-0 rounded-lg border border-border bg-background">
      <div className="flex flex-col gap-2 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-medium text-foreground">Trades</h3>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              addedRowPending.current = true
              onAddRow()
            }}
          >
            <Plus />
            Add row
          </Button>
          <Button type="button" onClick={onSave} disabled={isSaving}>
            <Save />
            {isSaving ? 'Saving...' : 'Save trades'}
          </Button>
        </div>
      </div>

      <p id="trade-reorder-help" className="sr-only">
        Use Alt and the up or down arrow on a drag handle to move a trade.
      </p>
      <div
        ref={scrollRef}
        role="region"
        aria-label="Trades table"
        className="[overflow-anchor:none] [&>[data-slot=table-container]]:overflow-visible"
        onFocusCapture={(event) => {
          const row = (
            event.target as HTMLElement
          ).closest<HTMLTableRowElement>('[data-trade-row-id]')
          if (!row) return // Select menus are portalled outside the table.
          const direction = tabDirection.current
          tabDirection.current = 0
          setFocusedRowId(row.dataset.tradeRowId ?? null)
          if (
            direction &&
            !event.currentTarget.contains(event.relatedTarget as Node | null)
          ) {
            const index = direction > 0 ? 0 : rows.length - 1
            if (Number(row.dataset.index) !== index)
              focusRow(index, direction > 0 ? 'first' : 'last')
          }
        }}
        onKeyDown={(event) => {
          const target = event.target as HTMLElement
          const row = target.closest<HTMLTableRowElement>('[data-trade-row-id]')
          if (!row || !event.altKey || target.dataset.rowAction !== 'drag')
            return
          const direction =
            event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0
          if (!direction) return
          event.preventDefault()
          const index = Number(row.dataset.index)
          const destination = rows[index + direction]
          if (destination) {
            onReorderRow(rows[index].localId, destination.localId)
            focusRow(index + direction, 'drag')
          }
        }}
        onClick={(event) => {
          const button = (event.target as HTMLElement).closest(
            '[data-row-action="delete"]',
          )
          const row = button?.closest<HTMLTableRowElement>('[data-index]')
          if (row && rows.length > 1)
            focusRow(
              Math.min(Number(row.dataset.index), rows.length - 2),
              'last',
            )
        }}
        onDragOver={(event) => {
          if (!draggedRowId) return
          event.preventDefault()
          dragSpeed.current =
            event.clientY < headerHeight + 40
              ? -14
              : event.clientY > window.innerHeight - 80
                ? 14
                : 0
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null))
            dragSpeed.current = 0
        }}
      >
        <Table
          className="min-w-[1200px] table-fixed text-xs"
          aria-label="Trades"
          aria-rowcount={rows.length + 2}
        >
          <TableHeader
            ref={headerRef}
            className="sticky top-0 z-10 bg-background"
          >
            <TableRow aria-rowindex={1}>
              <TableHead className="w-[5%] text-right">Row</TableHead>
              <TableHead className="w-[16%]">Strategy</TableHead>
              <TableHead className="w-[8%]">Ticker</TableHead>
              <TableHead className="w-[9%]">Month</TableHead>
              <TableHead className="w-[7%] text-right">Size</TableHead>
              <TableHead className="w-[10%] text-right">Strike</TableHead>
              <TableHead className="w-[11%] text-right">Credit/Debit</TableHead>
              <TableHead className="w-[8%] text-right">Exit</TableHead>
              <TableHead className="w-[11%]">Status</TableHead>
              <TableHead className="w-[8%] text-right">P&L</TableHead>
              <TableHead className="w-[7%] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={11}
                  className="h-24 text-center text-muted-foreground"
                >
                  Add a row to start logging this tracker.
                </TableCell>
              </TableRow>
            ) : (
              virtualRows.map((virtualRow, index) => {
                const row = rows[virtualRow.index]
                const previousEnd = index
                  ? virtualRows[index - 1].end
                  : bodyOffset
                return (
                  <Fragment key={row.localId}>
                    <RowSpacer height={virtualRow.start - previousEnd} />
                    <TradeRow
                      index={virtualRow.index}
                      measureRef={virtualizer.measureElement}
                      row={row}
                      pnl={pnlByRowId.get(row.id ?? row.localId) ?? null}
                      strategies={strategies}
                      issues={issuesByRowId.get(row.localId) ?? EMPTY_ISSUES}
                      isDragging={draggedRowId === row.localId}
                      onDragStart={handleDragStart}
                      onDragEnd={handleDragEnd}
                      onDrop={handleDrop}
                      onDeleteRow={onDeleteRow}
                      onOpenStrategyDialog={onOpenStrategyDialog}
                      onUpdateRow={onUpdateRow}
                      onMenuOpenChange={handleMenuOpenChange}
                    />
                  </Fragment>
                )
              })
            )}
            <RowSpacer
              height={
                virtualizer.getTotalSize() -
                ((virtualRows.at(-1)?.end ?? bodyOffset) - bodyOffset)
              }
            />
          </TableBody>
          <TableFooter className="sticky bottom-0 z-10 bg-muted">
            <TableRow aria-rowindex={rows.length + 2}>
              <TableCell colSpan={9}>Total</TableCell>
              <TableCell className={footerTotal.className}>{footerTotal.text}</TableCell>
              <TableCell />
            </TableRow>
          </TableFooter>
        </Table>
      </div>
    </section>
  )
}

function RowSpacer({ height }: { height: number }) {
  return height > 0 ? (
    <tr aria-hidden="true">
      <td colSpan={11} className="border-0 p-0" style={{ height }} />
    </tr>
  ) : null
}
