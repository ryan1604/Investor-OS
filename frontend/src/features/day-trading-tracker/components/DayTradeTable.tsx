import { Plus, Save, Trash2 } from 'lucide-react'

import { FieldIssue, NumberCell } from '@/components/EditableTableCells'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { calculateDayTradingStats, type DayTradeDraftField, type DayTradeDraftIssue, type DayTradeDraftRow } from '@/features/day-trading-tracker/lib/dayTradingTracker'
import { formatCurrency } from '@/lib/format'

export function DayTradeTable({
  date,
  issues,
  rows,
  stats,
  isSaving,
  onAddRow,
  onDeleteRow,
  onSave,
  onUpdateRow,
}: {
  date: string
  issues: DayTradeDraftIssue[]
  rows: DayTradeDraftRow[]
  stats: ReturnType<typeof calculateDayTradingStats>
  isSaving: boolean
  onAddRow: () => void
  onDeleteRow: (localId: string) => void
  onSave: () => void
  onUpdateRow: (
    localId: string,
    field: DayTradeDraftField,
    value: string,
  ) => void
}) {
  return (
    <section className="border-b border-border bg-muted/10">
      <div className="flex flex-col gap-3 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <h2 className="font-medium">{date}</h2>
          <Badge variant="outline">{formatCurrency(stats.pnl)}</Badge>
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onAddRow}>
            <Plus />
            Add row
          </Button>
          <Button type="button" onClick={onSave} disabled={isSaving}>
            <Save />
            {isSaving ? 'Saving...' : 'Save trades'}
          </Button>
        </div>
      </div>

      <Table className="table-fixed text-xs">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[23%] text-right">Buy</TableHead>
            <TableHead className="w-[23%] text-right">Sell</TableHead>
            <TableHead className="w-[19%] text-right">Size</TableHead>
            <TableHead className="w-[19%] text-right">Fee</TableHead>
            <TableHead className="w-[16%] text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={5}
                className="h-20 text-center text-muted-foreground"
              >
                Add a row to log trades for this day.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row, index) => (
              <TableRow key={row.localId}>
                <TableCell>
                  <NumberCell
                    className="text-right tabular-nums"
                    label={`Buy row ${index + 1}`}
                    value={row.buy}
                    onChange={(value) => onUpdateRow(row.localId, 'buy', value)}
                  />
                  <FieldIssue className="mt-1 text-left text-xs text-destructive" issues={issues} localId={row.localId} field="buy" />
                </TableCell>
                <TableCell>
                  <NumberCell
                    className="text-right tabular-nums"
                    label={`Sell row ${index + 1}`}
                    value={row.sell}
                    onChange={(value) => onUpdateRow(row.localId, 'sell', value)}
                  />
                  <FieldIssue className="mt-1 text-left text-xs text-destructive" issues={issues} localId={row.localId} field="sell" />
                </TableCell>
                <TableCell>
                  <NumberCell
                    className="text-right tabular-nums"
                    label={`Size row ${index + 1}`}
                    value={row.size}
                    onChange={(value) => onUpdateRow(row.localId, 'size', value)}
                  />
                  <FieldIssue className="mt-1 text-left text-xs text-destructive" issues={issues} localId={row.localId} field="size" />
                </TableCell>
                <TableCell>
                  <NumberCell
                    className="text-right tabular-nums"
                    label={`Fee row ${index + 1}`}
                    value={row.fee}
                    onChange={(value) => onUpdateRow(row.localId, 'fee', value)}
                  />
                  <FieldIssue className="mt-1 text-left text-xs text-destructive" issues={issues} localId={row.localId} field="fee" />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Delete row ${index + 1}`}
                      onClick={() => onDeleteRow(row.localId)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell colSpan={3}>Total</TableCell>
            <TableCell className="text-right tabular-nums">
              {stats.completedTrades} trades
            </TableCell>
            <TableCell className="text-right font-medium tabular-nums">
              {formatCurrency(stats.pnl)}
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </section>
  )
}
