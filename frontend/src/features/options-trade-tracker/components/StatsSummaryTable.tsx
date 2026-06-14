import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatAverage,
  formatPnl,
  OPTIONS_TRADE_MONTH_LABELS,
  OPTIONS_TRADE_MONTHS,
  type StrategyStatsTable,
} from '@/features/options-trade-tracker/lib/tradeTracker'
import { formatNumber } from '@/lib/format'

type StatsSummaryTableProps = {
  stats: StrategyStatsTable
}

export function StatsSummaryTable({ stats }: StatsSummaryTableProps) {
  return (
    <section className="rounded-lg border border-border bg-background">
      <div className="border-b border-border p-3">
        <h3 className="font-medium text-foreground">Summary</h3>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-36">Strategy</TableHead>
            {OPTIONS_TRADE_MONTHS.map((month) => (
              <TableHead key={month} className="text-right">
                {OPTIONS_TRADE_MONTH_LABELS[month]}
              </TableHead>
            ))}
            <TableHead className="text-right">Total</TableHead>
            <TableHead className="text-right">Count</TableHead>
            <TableHead className="text-right">Average</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {stats.rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={16}
                className="h-24 text-center text-muted-foreground"
              >
                Add a global strategy to start the stats table.
              </TableCell>
            </TableRow>
          ) : (
            stats.rows.map((row) => (
              <TableRow key={row.strategy}>
                <TableCell className="font-medium">{row.strategy}</TableCell>
                {OPTIONS_TRADE_MONTHS.map((month) => (
                  <CurrencyCell key={month} value={row.months[month]} />
                ))}
                <CurrencyCell value={row.total} strong />
                <TableCell className="text-right tabular-nums">
                  {formatNumber(row.count)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatAverage(row.average)}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell>Total</TableCell>
            {OPTIONS_TRADE_MONTHS.map((month) => (
              <CurrencyCell key={month} value={stats.monthTotals[month]} />
            ))}
            <CurrencyCell value={stats.total} strong />
            <TableCell className="text-right tabular-nums">
              {formatNumber(stats.count)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatAverage(stats.average)}
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </section>
  )
}

function CurrencyCell({
  value,
  strong = false,
}: {
  value: number
  strong?: boolean
}) {
  return (
    <TableCell
      className={`text-right tabular-nums ${strong ? 'font-medium' : ''}`}
    >
      {formatPnl(value)}
    </TableCell>
  )
}
