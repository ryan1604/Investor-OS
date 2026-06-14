import { useState, type DragEvent } from 'react'
import { GripVertical, Plus, Save, Trash2 } from 'lucide-react'

import type {
  OptionsTradeMonth,
  OptionsTradeStatus,
} from '@/api/optionsTradeTrackers'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StrategySelectCell } from '@/features/options-trade-tracker/components/StrategyComboboxCell'
import {
  calculateTradesFooterTotal,
  formatCurrencyInput,
  formatPnl,
  normalizeTickerDraft,
  OPTIONS_TRADE_MONTH_LABELS,
  OPTIONS_TRADE_MONTHS,
  parseCurrencyInput,
  type CompletedTradeProjection,
  type TradeDraftField,
  type TradeDraftRow,
  type TradeDraftValidationIssue,
} from '@/features/options-trade-tracker/lib/tradeTracker'

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

const statuses: OptionsTradeStatus[] = ['In Progress', 'Completed']

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
  const pnlByRowId = new Map(
    completedTrades.map(({ row, pnl }) => [row.id, pnl]),
  )
  const footerTotal = calculateTradesFooterTotal(completedTrades)

  function handleDragStart(event: DragEvent<HTMLTableRowElement>, localId: string) {
    setDraggedRowId(localId)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', localId)
  }

  function handleDragOver(event: DragEvent<HTMLTableRowElement>) {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }

  function handleDrop(event: DragEvent<HTMLTableRowElement>, targetLocalId: string) {
    event.preventDefault()
    const draggedLocalId =
      event.dataTransfer.getData('text/plain') || draggedRowId

    if (draggedLocalId && draggedLocalId !== targetLocalId) {
      onReorderRow(draggedLocalId, targetLocalId)
    }

    setDraggedRowId(null)
  }

  return (
    <section className="rounded-lg border border-border bg-background">
      <div className="flex flex-col gap-2 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-medium text-foreground">Trades</h3>
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

      <Table className="min-w-[1280px] table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-52">Strategy</TableHead>
            <TableHead className="w-36">Ticker</TableHead>
            <TableHead className="w-32">Month</TableHead>
            <TableHead className="w-32 text-right">Size</TableHead>
            <TableHead className="w-40 text-right">Strike Price</TableHead>
            <TableHead className="w-40 text-right">Credit/Debit</TableHead>
            <TableHead className="w-36 text-right">Exit</TableHead>
            <TableHead className="w-44">Status</TableHead>
            <TableHead className="w-32 text-right">P&L</TableHead>
            <TableHead className="w-28 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={10} className="h-24 text-center text-muted-foreground">
                Add a row to start logging this tracker.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => {
              const pnl = pnlByRowId.get(row.id ?? row.localId) ?? null
              const rowIssue = issues.find(
                (issue) => issue.localId === row.localId && issue.field === 'row',
              )

              return (
                <TableRow
                  key={row.localId}
                  draggable
                  data-state={draggedRowId === row.localId ? 'selected' : undefined}
                  className="cursor-grab active:cursor-grabbing"
                  onDragStart={(event) => handleDragStart(event, row.localId)}
                  onDragEnd={() => setDraggedRowId(null)}
                  onDragOver={handleDragOver}
                  onDrop={(event) => handleDrop(event, row.localId)}
                >
                  <TableCell>
                    <StrategySelectCell
                      id={row.localId}
                      value={row.strategy}
                      strategies={strategies}
                      onChange={(value) =>
                        onUpdateRow(row.localId, 'strategy', value)
                      }
                      onAddStrategy={onOpenStrategyDialog}
                    />
                    <FieldIssue issues={issues} localId={row.localId} field="strategy" />
                  </TableCell>
                  <TableCell>
                    <Input
                      aria-label={`Ticker row ${row.localId}`}
                      className="w-24 uppercase"
                      value={row.ticker}
                      onChange={(event) =>
                        onUpdateRow(
                          row.localId,
                          'ticker',
                          normalizeTickerDraft(event.target.value),
                        )
                      }
                      placeholder="AAPL"
                    />
                  </TableCell>
                  <TableCell>
                    <Select
                      value={row.month}
                      onValueChange={(value) =>
                        onUpdateRow(
                          row.localId,
                          'month',
                          value as OptionsTradeMonth,
                        )
                      }
                    >
                      <SelectTrigger
                        aria-label={`Month row ${row.localId}`}
                        className="w-24"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {OPTIONS_TRADE_MONTHS.map((month) => (
                          <SelectItem key={month} value={month}>
                            {OPTIONS_TRADE_MONTH_LABELS[month]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-right">
                    <NumberCell
                      label={`Size row ${row.localId}`}
                      value={row.size}
                      onChange={(value) => onUpdateRow(row.localId, 'size', value)}
                    />
                    <FieldIssue issues={issues} localId={row.localId} field="size" />
                  </TableCell>
                  <TableCell className="text-right">
                    <NumberCell
                      label={`Strike price row ${row.localId}`}
                      value={row.strikePrice}
                      onChange={(value) =>
                        onUpdateRow(row.localId, 'strikePrice', value)
                      }
                      format="currency"
                    />
                    <FieldIssue
                      issues={issues}
                      localId={row.localId}
                      field="strikePrice"
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <NumberCell
                      label={`Credit debit row ${row.localId}`}
                      value={row.creditDebit}
                      onChange={(value) =>
                        onUpdateRow(row.localId, 'creditDebit', value)
                      }
                      format="currency"
                    />
                    <FieldIssue
                      issues={issues}
                      localId={row.localId}
                      field="creditDebit"
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <NumberCell
                      label={`Exit row ${row.localId}`}
                      value={row.exit}
                      onChange={(value) => onUpdateRow(row.localId, 'exit', value)}
                      format="currency"
                    />
                    <FieldIssue issues={issues} localId={row.localId} field="exit" />
                  </TableCell>
                  <TableCell>
                    <Select
                      value={row.status}
                      onValueChange={(value) =>
                        onUpdateRow(
                          row.localId,
                          'status',
                          value as OptionsTradeStatus,
                        )
                      }
                    >
                      <SelectTrigger
                        aria-label={`Status row ${row.localId}`}
                        className="w-32"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {statuses.map((status) => (
                          <SelectItem key={status} value={status}>
                            {status}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {rowIssue ? (
                      <div className="mt-1 max-w-48 text-xs text-destructive">
                        {rowIssue.message}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right font-medium">
                    {formatPnl(pnl)}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Drag row ${row.localId}`}
                        className="cursor-grab active:cursor-grabbing"
                      >
                        <GripVertical />
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Delete row ${row.localId}`}
                        onClick={() => onDeleteRow(row.localId)}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell colSpan={8}>Total</TableCell>
            <TableCell className="text-right">{formatPnl(footerTotal)}</TableCell>
            <TableCell />
          </TableRow>
        </TableFooter>
      </Table>
    </section>
  )
}

function NumberCell({
  label,
  value,
  format = 'number',
  onChange,
}: {
  label: string
  value: string
  format?: 'currency' | 'number'
  onChange: (value: string) => void
}) {
  const [isFocused, setIsFocused] = useState(false)
  const displayValue =
    format === 'currency' && !isFocused ? formatCurrencyDraft(value) : value

  return (
    <Input
      aria-label={label}
      className="w-28 text-right tabular-nums"
      inputMode="decimal"
      value={displayValue}
      onFocus={() => setIsFocused(true)}
      onBlur={() => setIsFocused(false)}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function formatCurrencyDraft(value: string) {
  const parsedValue = parseCurrencyInput(value, {
    allowBlank: true,
    allowZero: true,
  })

  return typeof parsedValue === 'number' ? formatCurrencyInput(parsedValue) : value
}

function FieldIssue({
  issues,
  localId,
  field,
}: {
  issues: TradeDraftValidationIssue[]
  localId: string
  field: TradeDraftField
}) {
  const issue = issues.find(
    (candidate) => candidate.localId === localId && candidate.field === field,
  )

  return issue ? (
    <div className="mt-1 max-w-44 text-xs text-destructive">{issue.message}</div>
  ) : null
}
