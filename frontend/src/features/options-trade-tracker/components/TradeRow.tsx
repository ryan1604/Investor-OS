import { memo, useState, type DragEvent } from 'react'
import { GripVertical, Trash2 } from 'lucide-react'

import type {
  OptionsTradeMonth,
  OptionsTradeStatus,
} from '@/api/optionsTradeTrackers'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { TableCell, TableRow } from '@/components/ui/table'
import { daysToExpiration } from '@/features/options-screeners/lib/expiration'
import { StrategySelectCell } from '@/features/options-trade-tracker/components/StrategyComboboxCell'
import {
  formatCurrencyInput,
  formatPnl,
  normalizeTickerDraft,
  OPTIONS_TRADE_MONTH_LABELS,
  OPTIONS_TRADE_MONTHS,
  parseCurrencyInput,
  type TradeDraftField,
  type TradeDraftRow,
  type TradeDraftValidationIssue,
} from '@/features/options-trade-tracker/lib/tradeTracker'
import { signedValueClassName } from '@/lib/format'

type TradeRowProps = {
  index: number
  measureRef: (element: HTMLTableRowElement | null) => void
  row: TradeDraftRow
  pnl: number | null
  strategies: string[]
  issues: TradeDraftValidationIssue[]
  isDragging: boolean
  onDragStart: (event: DragEvent<HTMLTableRowElement>, localId: string) => void
  onDragEnd: () => void
  onDrop: (event: DragEvent<HTMLTableRowElement>, localId: string) => void
  onDeleteRow: (localId: string) => void
  onOpenStrategyDialog: () => void
  onMenuOpenChange: (localId: string, open: boolean) => void
  onUpdateRow: (localId: string, field: TradeDraftField, value: string) => void
}

function isoDate(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

const statuses: OptionsTradeStatus[] = ['In Progress', 'Completed']

const monthColors: Record<OptionsTradeMonth, string> = {
  jan: 'bg-blue-500/10 text-blue-700 dark:bg-blue-400/15 dark:text-blue-300',
  feb: 'bg-cyan-500/10 text-cyan-700 dark:bg-cyan-400/15 dark:text-cyan-300',
  mar: 'bg-teal-500/10 text-teal-700 dark:bg-teal-400/15 dark:text-teal-300',
  apr: 'bg-emerald-500/10 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300',
  may: 'bg-lime-500/10 text-lime-700 dark:bg-lime-400/15 dark:text-lime-300',
  jun: 'bg-amber-500/10 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300',
  jul: 'bg-orange-500/10 text-orange-700 dark:bg-orange-400/15 dark:text-orange-300',
  aug: 'bg-red-500/10 text-red-700 dark:bg-red-400/15 dark:text-red-300',
  sep: 'bg-pink-500/10 text-pink-700 dark:bg-pink-400/15 dark:text-pink-300',
  oct: 'bg-fuchsia-500/10 text-fuchsia-700 dark:bg-fuchsia-400/15 dark:text-fuchsia-300',
  nov: 'bg-violet-500/10 text-violet-700 dark:bg-violet-400/15 dark:text-violet-300',
  dec: 'bg-indigo-500/10 text-indigo-700 dark:bg-indigo-400/15 dark:text-indigo-300',
}

export const TradeRow = memo(function TradeRow({
  index,
  measureRef,
  row,
  pnl,
  strategies,
  issues,
  isDragging,
  onDragStart,
  onDragEnd,
  onDrop,
  onDeleteRow,
  onOpenStrategyDialog,
  onMenuOpenChange,
  onUpdateRow,
}: TradeRowProps) {
  const rowIssue = issues.find((issue) => issue.field === 'row')
  const expiryDate = row.expiryDate
    ? new Date(`${row.expiryDate}T00:00:00`)
    : undefined

  return (
    <TableRow
      ref={measureRef}
      data-index={index}
      data-trade-row-id={row.localId}
      aria-rowindex={index + 2}
      draggable
      data-state={isDragging ? 'selected' : undefined}
      className="cursor-grab active:cursor-grabbing"
      onDragStart={(event) => onDragStart(event, row.localId)}
      onDragEnd={onDragEnd}
      onDragOver={handleDragOver}
      onDrop={(event) => onDrop(event, row.localId)}
    >
      <TableCell className="text-right tabular-nums text-muted-foreground">
        {index + 1}
      </TableCell>
      <TableCell>
        <StrategySelectCell
          id={row.localId}
          value={row.strategy}
          strategies={strategies}
          onChange={(value) => onUpdateRow(row.localId, 'strategy', value)}
          onAddStrategy={onOpenStrategyDialog}
          onOpenChange={(open) => onMenuOpenChange(row.localId, open)}
        />
        <FieldIssue issues={issues} localId={row.localId} field="strategy" />
      </TableCell>
      <TableCell>
        <Input
          aria-label={`Ticker row ${row.localId}`}
          className="w-full uppercase"
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
        <Popover onOpenChange={(open) => onMenuOpenChange(row.localId, open)}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              aria-label={`Month row ${row.localId}`}
              className="w-full justify-start px-2 font-normal"
            >
              <span className={`rounded-sm px-1.5 py-0.5 text-xs font-medium ${monthColors[row.month]}`}>
                {OPTIONS_TRADE_MONTH_LABELS[row.month]}
                {row.expiryDate && ` - ${daysToExpiration(row.expiryDate)} DTE`}
              </span>
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="single"
              selected={expiryDate}
              defaultMonth={expiryDate}
              onSelect={(date) => {
                if (!date) return
                onUpdateRow(row.localId, 'expiryDate', isoDate(date))
                onUpdateRow(row.localId, 'month', OPTIONS_TRADE_MONTHS[date.getMonth()])
              }}
            />
          </PopoverContent>
        </Popover>
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
          onChange={(value) => onUpdateRow(row.localId, 'strikePrice', value)}
          format="currency"
        />
        <FieldIssue issues={issues} localId={row.localId} field="strikePrice" />
      </TableCell>
      <TableCell className="text-right">
        <NumberCell
          label={`Credit debit row ${row.localId}`}
          value={row.creditDebit}
          onChange={(value) => onUpdateRow(row.localId, 'creditDebit', value)}
          format="currency"
        />
        <FieldIssue issues={issues} localId={row.localId} field="creditDebit" />
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
          onOpenChange={(open) => onMenuOpenChange(row.localId, open)}
          onValueChange={(value) =>
            onUpdateRow(row.localId, 'status', value as OptionsTradeStatus)
          }
        >
          <SelectTrigger
            aria-label={`Status row ${row.localId}`}
            className="w-full"
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
          <div className="mt-1 max-w-48 whitespace-normal text-xs text-destructive">
            {rowIssue.message}
          </div>
        ) : null}
      </TableCell>
      <TableCell className={`${signedValueClassName(pnl)} font-medium`}>
        {formatPnl(pnl)}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label={`Drag row ${row.localId}`}
            aria-describedby="trade-reorder-help"
            data-row-action="drag"
            className="cursor-grab active:cursor-grabbing"
          >
            <GripVertical />
          </Button>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label={`Delete row ${row.localId}`}
            data-row-action="delete"
            onClick={() => onDeleteRow(row.localId)}
          >
            <Trash2 />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
})

function handleDragOver(event: DragEvent<HTMLTableRowElement>) {
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
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
      className="w-full text-right tabular-nums"
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

  return typeof parsedValue === 'number'
    ? formatCurrencyInput(parsedValue)
    : value
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
    <div className="mt-1 max-w-44 whitespace-normal text-xs text-destructive">
      {issue.message}
    </div>
  ) : null
}
