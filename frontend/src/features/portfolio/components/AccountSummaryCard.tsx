import type { PortfolioAccountSummary } from '@/api/portfolio'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  formatOptionalCurrency,
  formatOptionalPercent,
  signedTextClassName,
} from '@/lib/format'

type AccountMetricProps = {
  label: string
  value: string
  valueClassName?: string
  detail?: string
}

function AccountMetric({
  label,
  value,
  valueClassName = 'text-foreground',
  detail,
}: AccountMetricProps) {
  return (
    <div className="min-w-0 border-t pt-3 first:border-t-0 first:pt-0 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0 sm:first:border-l-0 sm:first:pl-0">
      <div className="text-xs font-medium uppercase tracking-normal text-muted-foreground">
        {label}
      </div>
      <div
        className={[
          'mt-1 flex min-h-8 min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5',
          valueClassName,
        ].join(' ')}
      >
        <span className="truncate text-xl font-semibold tabular-nums leading-tight">
          {value}
        </span>
        {detail ? (
          <span className="text-sm font-medium tabular-nums">{detail}</span>
        ) : null}
      </div>
    </div>
  )
}

function equityPercent(summary: PortfolioAccountSummary) {
  if (summary.net_liquidation === null || summary.market_value === null) {
    return null
  }

  return (summary.net_liquidation / summary.market_value) * 100
}

function equityPercentClassName(value: number | null) {
  if (value === null) {
    return 'text-foreground'
  }

  return value >= 50 ? 'text-emerald-500' : 'text-red-500'
}

type AccountSummaryCardProps = {
  isLoading: boolean
  summary: PortfolioAccountSummary | null
}

export function AccountSummaryCard({
  isLoading,
  summary,
}: AccountSummaryCardProps) {
  const summaryEquityPercent = summary ? equityPercent(summary) : null

  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
            {Array.from({ length: 11 }).map((_, index) => (
              <div
                key={index}
                className="border-t pt-3 first:border-t-0 first:pt-0 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0 sm:first:border-l-0 sm:first:pl-0"
              >
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-2 h-8 w-36" />
              </div>
            ))}
          </div>
        ) : summary ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
            <AccountMetric
              label="Net Liquidation"
              value={formatOptionalCurrency(
                summary.net_liquidation,
                summary.currency,
              )}
            />
            <AccountMetric
              label="Daily P&L"
              value={formatOptionalCurrency(summary.daily_pnl, summary.currency)}
              valueClassName={signedTextClassName(summary.daily_pnl)}
              detail={formatOptionalPercent(summary.daily_pnl_percent)}
            />
            <AccountMetric
              label="Unrealized P&L"
              value={formatOptionalCurrency(
                summary.unrealized_pnl,
                summary.currency,
              )}
              valueClassName={signedTextClassName(summary.unrealized_pnl)}
            />
            <AccountMetric
              label="Market Value"
              value={formatOptionalCurrency(
                summary.market_value,
                summary.currency,
              )}
            />
            <AccountMetric
              label="Equity %"
              value={formatOptionalPercent(summaryEquityPercent)}
              valueClassName={equityPercentClassName(summaryEquityPercent)}
            />
            <AccountMetric
              label="Maintenance Margin"
              value={formatOptionalCurrency(
                summary.maintenance_margin,
                summary.currency,
              )}
            />
            <AccountMetric
              label="Excess Liquidity"
              value={formatOptionalCurrency(
                summary.excess_liquidity,
                summary.currency,
              )}
            />
            <AccountMetric
              label="Buying Power"
              value={formatOptionalCurrency(summary.buying_power, summary.currency)}
            />
            <AccountMetric
              label="Total SGD"
              value={formatOptionalCurrency(summary.cash_total_sgd, 'SGD')}
            />
            <AccountMetric
              label="Total USD"
              value={formatOptionalCurrency(summary.cash_total_usd, 'USD')}
            />
            <AccountMetric
              label="Total"
              value={formatOptionalCurrency(summary.cash_total, summary.currency)}
            />
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            No account summary returned yet.
          </div>
        )}
      </CardContent>
    </Card>
  )
}
