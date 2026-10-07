import type {
  AnalysisMarginEstimate,
  AnalysisStressCell,
  AnalysisStressGrid,
} from '@/api/portfolioAnalysis'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Metric } from '@/features/portfolio-analysis/components/AnalysisSummaryCards'
import {
  formatShock,
  formatWholeCurrency,
  marginCallDistanceText,
} from '@/features/portfolio-analysis/lib/format'
import { limitTextClass, type LimitBands } from '@/features/portfolio-analysis/lib/limits'
import { formatOptionalPercent, signedTextClassName } from '@/lib/format'
import { cn } from '@/lib/utils'

const HEADER_CLASS = 'text-right text-xs uppercase text-muted-foreground'

function isMarginCall(cell: AnalysisStressCell) {
  return cell.excess_liquidity !== null && cell.excess_liquidity < 0
}

function StressValueCell({ cell }: { cell: AnalysisStressCell | undefined }) {
  if (!cell) {
    return <TableCell className="text-right">-</TableCell>
  }

  const marginCall = isMarginCall(cell)
  const excess = formatWholeCurrency(cell.excess_liquidity)
  return (
    <TableCell
      className={cn(
        'text-right tabular-nums',
        marginCall && 'bg-red-500/15',
        cell.realistic_path && 'ring-1 ring-inset ring-sky-500/70',
      )}
      data-margin-call={marginCall || undefined}
      data-realistic-path={cell.realistic_path || undefined}
      title={`Stressed excess liquidity: ${excess}`}
    >
      <div className={cn('font-medium', signedTextClassName(cell.pnl))}>
        {formatWholeCurrency(cell.pnl)}
      </div>
      <div className="text-muted-foreground">{formatOptionalPercent(cell.pnl_percent)}</div>
    </TableCell>
  )
}

function marginNote(margin: AnalysisMarginEstimate) {
  const excluded = margin.excluded_groups
    ? ` ${margin.excluded_groups} strategy group(s) without prices add no P&L or margin.`
    : ''
  return (
    'Estimate: the SPY drop along the realistic path at which excess liquidity reaches zero. ' +
    `Reg T model margin ${formatWholeCurrency(margin.model_margin)} x calibration factor ` +
    `${margin.calibration_factor.toFixed(2)} (IB maintenance margin ` +
    `${formatWholeCurrency(margin.ib_maintenance_margin)}).${excluded}`
  )
}

type StressSummaryCardsProps = {
  stress: AnalysisStressGrid
  // Band colours for metrics with a saved risk limit.
  bands?: LimitBands
}

export function StressSummaryCards({ stress, bands = {} }: StressSummaryCardsProps) {
  const down20 = stress.realistic_path.find((cell) => cell.spy_move_percent === -20)

  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        <div className="grid gap-4 sm:grid-cols-2">
          <Metric
            label="Realistic -20% P&L (Est.)"
            value={formatOptionalPercent(down20?.pnl_percent ?? null)}
            detail={formatWholeCurrency(down20?.pnl ?? null)}
            note={
              down20
                ? `Estimate: SPY ${formatShock(down20.spy_move_percent)} with IV ` +
                  `${formatShock(down20.iv_shock_percent)} (scaled by beta), repriced with ` +
                  'Black-Scholes and no time decay.'
                : undefined
            }
            valueClassName={limitTextClass(
              bands,
              'realistic_path_loss_percent',
              signedTextClassName(down20?.pnl ?? null),
            )}
          />
          <Metric
            label="Distance to Margin Call (Est.)"
            value={marginCallDistanceText(stress.margin)}
            detail={
              stress.margin.distance_to_margin_call_percent !== null ? 'SPY drop' : undefined
            }
            note={marginNote(stress.margin)}
            valueClassName={limitTextClass(bands, 'margin_call_distance_percent')}
          />
        </div>
      </CardContent>
    </Card>
  )
}

export function StressGridTable({ stress }: { stress: AnalysisStressGrid }) {
  const cellAt = (spyMove: number, ivShock: number) =>
    stress.cells.find(
      (cell) => cell.spy_move_percent === spyMove && cell.iv_shock_percent === ivShock,
    )

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Stress Test (Estimates)</CardTitle>
        <p className="text-sm text-muted-foreground">
          Estimated P&amp;L for instant shocks: each underlying moves by beta x SPY, IV rises by
          the shock scaled by beta, and options are repriced with Black-Scholes with no time
          decay. Red cells have negative stressed excess liquidity; outlined cells are on the
          realistic path.
          {stress.excluded_legs
            ? ` ${stress.excluded_legs} leg(s) are left out because their strategy group ` +
              'has a leg without a price or IV.'
            : ''}
        </p>
      </CardHeader>
      <CardContent className="pt-0">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs uppercase text-muted-foreground">SPY Move</TableHead>
              {stress.iv_shocks_percent.map((shock) => (
                <TableHead key={shock} className={HEADER_CLASS}>
                  IV {formatShock(shock)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {stress.spy_moves_percent.map((move) => (
              <TableRow key={move}>
                <TableHead scope="row" className="font-medium text-foreground">
                  {formatShock(move)}
                </TableHead>
                {stress.iv_shocks_percent.map((shock) => (
                  <StressValueCell key={shock} cell={cellAt(move, shock)} />
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>

        <Table className="mt-4 text-xs" aria-label="Realistic path">
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs uppercase text-muted-foreground">
                Realistic Path
              </TableHead>
              {stress.realistic_path.map((cell) => (
                <TableHead key={cell.spy_move_percent} className={HEADER_CLASS}>
                  SPY {formatShock(cell.spy_move_percent)} / IV {formatShock(cell.iv_shock_percent)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableHead scope="row" className="font-medium text-foreground">
                P&amp;L
              </TableHead>
              {stress.realistic_path.map((cell) => (
                <StressValueCell key={cell.spy_move_percent} cell={cell} />
              ))}
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
