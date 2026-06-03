import { ArrowDown, ArrowDownUp, ArrowUp } from 'lucide-react'

import { Alert } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type {
  DisplayPosition,
  SortKey,
  SortState,
} from '@/features/portfolio/lib/positions'
import { POSITIONS_TABLE_COLUMNS } from '@/features/portfolio/lib/tableColumns'
import {
  formatNumber,
  formatOptionalCurrency,
  formatOptionalPercent,
  signedValueClassName,
} from '@/lib/format'

type SortableTableHeadProps = {
  label: string
  sortKey: SortKey
  sort: SortState
  align?: 'left' | 'right'
  onSort: (key: SortKey) => void
}

function SortableTableHead({
  label,
  sortKey,
  sort,
  align = 'left',
  onSort,
}: SortableTableHeadProps) {
  const isActive = sort.key === sortKey
  const SortIcon = isActive
    ? sort.direction === 'asc'
      ? ArrowUp
      : ArrowDown
    : ArrowDownUp
  const ariaSort = isActive
    ? sort.direction === 'asc'
      ? 'ascending'
      : 'descending'
    : 'none'

  return (
    <TableHead
      aria-sort={ariaSort}
      className={align === 'right' ? 'text-right' : undefined}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={[
          'inline-flex w-full cursor-pointer items-center gap-1.5 rounded-sm text-xs font-medium uppercase tracking-normal text-muted-foreground transition-colors hover:text-foreground active:cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          align === 'right' ? 'justify-end' : 'justify-start',
          isActive ? 'text-foreground' : '',
        ].join(' ')}
      >
        <span>{label}</span>
        <SortIcon className="size-3.5 shrink-0" />
      </button>
    </TableHead>
  )
}

type PositionsTableProps = {
  error: string | null
  isConnected: boolean
  isLoading: boolean
  positions: DisplayPosition[]
  sort: SortState
  onSort: (key: SortKey) => void
}

function positionKey(position: DisplayPosition, index: number) {
  return [
    position.account,
    position.symbol,
    position.sec_type,
    position.expiry,
    position.strike,
    position.right,
    position.exchange,
    position.currency,
    position.quantity,
    position.average_cost,
    position.instrumentTitle,
    position.instrumentDetail,
    index,
  ].join('-')
}

export function PositionsTable({
  error,
  isConnected,
  isLoading,
  positions,
  sort,
  onSort,
}: PositionsTableProps) {
  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        {error ? (
          <Alert variant="destructive" className="mb-4">
            {error}
          </Alert>
        ) : null}
        {!error && !isConnected && !isLoading ? (
          <Alert variant="muted" className="mb-4">
            Start TWS or IB Gateway paper trading, then refresh this view.
          </Alert>
        ) : null}

        <Table>
          <TableHeader>
            <TableRow>
              {POSITIONS_TABLE_COLUMNS.map((column) => (
                <SortableTableHead
                  key={column.sortKey}
                  label={column.label}
                  sortKey={column.sortKey}
                  sort={sort}
                  align={column.align}
                  onSort={onSort}
                />
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, index) => (
                <TableRow key={index}>
                  {POSITIONS_TABLE_COLUMNS.map((column) => (
                    <TableCell key={column.sortKey}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : positions.length ? (
              positions.map((position, index) => (
                <TableRow key={positionKey(position, index)}>
                  <TableCell className="min-w-56 font-medium">
                    <div className="flex flex-col gap-0.5">
                      <span>{position.instrumentTitle}</span>
                      {position.instrumentDetail ? (
                        <span className="text-xs font-normal text-muted-foreground">
                          {position.instrumentDetail}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    {formatOptionalCurrency(
                      position.last_price,
                      position.currency || 'USD',
                    )}
                  </TableCell>
                  <TableCell
                    className={signedValueClassName(position.change_percent)}
                  >
                    {formatOptionalPercent(position.change_percent)}
                  </TableCell>
                  <TableCell className={signedValueClassName(position.pnl)}>
                    {formatOptionalCurrency(position.pnl, position.currency || 'USD')}
                  </TableCell>
                  <TableCell
                    className={signedValueClassName(position.pnl_percent)}
                  >
                    {formatOptionalPercent(position.pnl_percent)}
                  </TableCell>
                  <TableCell
                    className={signedValueClassName(position.unrealized_pnl)}
                  >
                    {formatOptionalCurrency(
                      position.unrealized_pnl,
                      position.currency || 'USD',
                    )}
                  </TableCell>
                  <TableCell
                    className={signedValueClassName(
                      position.unrealized_pnl_percent,
                    )}
                  >
                    {formatOptionalPercent(position.unrealized_pnl_percent)}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatOptionalCurrency(
                      position.market_value,
                      position.currency || 'USD',
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatNumber(position.quantity, {
                      maximumFractionDigits: 4,
                    })}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatOptionalCurrency(
                      position.cost_basis,
                      position.currency || 'USD',
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatOptionalCurrency(
                      position.average_price,
                      position.currency || 'USD',
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatOptionalPercent(position.net_liquidity_percent)}
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={POSITIONS_TABLE_COLUMNS.length}
                  className="h-24 text-center text-muted-foreground"
                >
                  No positions returned yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
