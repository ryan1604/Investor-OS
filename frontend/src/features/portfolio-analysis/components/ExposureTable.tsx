import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import type {
  AnalysisExposure,
  AnalysisGroup,
  AnalysisLeg,
  AnalysisUnderlying,
} from '@/api/portfolioAnalysis'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FallbackIndicator } from '@/features/portfolio-analysis/components/FallbackIndicator'
import {
  betaFallbackNote,
  formatWholeCurrency,
  legLabel,
  legNotes,
} from '@/features/portfolio-analysis/lib/format'
import { formatNumber, signedValueClassName } from '@/lib/format'

const COLUMNS = [
  'Dollar Delta',
  'Beta',
  'Beta-Wtd Delta',
  'Theta / Day',
  'Vega',
  'Max Loss',
  'Assignment',
]

type ExpandButtonProps = {
  expanded: boolean
  label: string
  onToggle: () => void
  children: ReactNode
}

function ExpandButton({ expanded, label, onToggle, children }: ExpandButtonProps) {
  const Icon = expanded ? ChevronDown : ChevronRight
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}`}
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-sm text-left hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={onToggle}
    >
      <Icon className="size-3.5 shrink-0" />
      {children}
    </button>
  )
}

function maxLossText(maxLoss: number | null, unlimited = maxLoss === null) {
  return unlimited ? 'Unlimited' : formatWholeCurrency(maxLoss)
}

function ExposureCells({
  exposure,
  beta,
  maxLoss,
  assignment,
}: {
  exposure: AnalysisExposure
  beta: ReactNode
  maxLoss: string
  assignment: number | null
}) {
  return (
    <>
      <TableCell className={signedValueClassName(exposure.dollar_delta)}>
        {formatWholeCurrency(exposure.dollar_delta)}
      </TableCell>
      <TableCell className="text-right">{beta}</TableCell>
      <TableCell className={signedValueClassName(exposure.beta_weighted_delta)}>
        {formatWholeCurrency(exposure.beta_weighted_delta)}
      </TableCell>
      <TableCell className={signedValueClassName(exposure.theta)}>
        {formatWholeCurrency(exposure.theta)}
      </TableCell>
      <TableCell className="text-right">{formatWholeCurrency(exposure.vega)}</TableCell>
      <TableCell className="text-right">{maxLoss}</TableCell>
      <TableCell className="text-right">
        {assignment ? formatWholeCurrency(assignment) : '-'}
      </TableCell>
    </>
  )
}

function LegRow({ leg }: { leg: AnalysisLeg }) {
  // A leg without Greeks or a price counts as 0 in totals but shows as missing.
  const isMissing = leg.greeks_source === 'missing' || leg.flags.includes('missing_price')

  return (
    <TableRow className="text-muted-foreground">
      <TableCell className="pl-14">
        <span className="inline-flex items-center gap-1.5">
          {legLabel(leg)}
          <FallbackIndicator notes={legNotes(leg)} />
        </span>
      </TableCell>
      {isMissing ? (
        <>
          {COLUMNS.map((column) => (
            <TableCell key={column} className="text-right">
              -
            </TableCell>
          ))}
        </>
      ) : (
        <ExposureCells exposure={leg} beta="-" maxLoss="-" assignment={null} />
      )}
    </TableRow>
  )
}

function GroupRows({ group, groupKey }: { group: AnalysisGroup; groupKey: string }) {
  const [expanded, setExpanded] = useState(false)
  const notes = group.legs.flatMap(legNotes)

  return (
    <>
      <TableRow>
        <TableCell className="pl-8">
          <ExpandButton
            expanded={expanded}
            label={`${groupKey} legs`}
            onToggle={() => setExpanded((current) => !current)}
          >
            <span>
              {group.label} x {formatNumber(group.quantity)}
            </span>
          </ExpandButton>{' '}
          <FallbackIndicator notes={notes.length ? ['Some legs use fallback values.'] : []} />
        </TableCell>
        <ExposureCells
          exposure={group}
          beta="-"
          maxLoss={maxLossText(group.max_loss)}
          assignment={group.assignment_exposure}
        />
      </TableRow>
      {expanded
        ? group.legs.map((leg, index) => (
            <LegRow key={`${leg.con_id}-${index}`} leg={leg} />
          ))
        : null}
    </>
  )
}

function UnderlyingRows({ underlying }: { underlying: AnalysisUnderlying }) {
  const [expanded, setExpanded] = useState(false)
  const betaNote = betaFallbackNote(underlying.beta_source, underlying.beta_observations)
  const beta = (
    <span className="inline-flex items-center gap-1">
      <FallbackIndicator notes={betaNote ? [betaNote] : []} />
      {formatNumber(underlying.beta, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}
      {underlying.beta_source === 'override' ? (
        <span className="text-muted-foreground" title="Beta override">
          (set)
        </span>
      ) : null}
    </span>
  )

  return (
    <>
      <TableRow className="font-medium">
        <TableCell>
          <ExpandButton
            expanded={expanded}
            label={`${underlying.symbol} strategies`}
            onToggle={() => setExpanded((current) => !current)}
          >
            <span>{underlying.symbol}</span>
          </ExpandButton>
        </TableCell>
        <ExposureCells
          exposure={underlying}
          beta={beta}
          maxLoss={maxLossText(underlying.max_loss, underlying.max_loss_unlimited)}
          assignment={underlying.assignment_exposure}
        />
      </TableRow>
      {expanded
        ? underlying.groups.map((group, index) => (
            <GroupRows
              key={`${group.kind}-${index}`}
              group={group}
              groupKey={`${underlying.symbol} ${group.label}`}
            />
          ))
        : null}
    </>
  )
}

type ExposureTableProps = {
  underlyings: AnalysisUnderlying[]
}

export function ExposureTable({ underlyings }: ExposureTableProps) {
  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs uppercase text-muted-foreground">Underlying</TableHead>
              {COLUMNS.map((column) => (
                <TableHead
                  key={column}
                  className="text-right text-xs uppercase text-muted-foreground"
                >
                  {column}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {underlyings.length ? (
              underlyings.map((underlying) => (
                <UnderlyingRows key={underlying.symbol} underlying={underlying} />
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={COLUMNS.length + 1} className="text-center text-muted-foreground">
                  No supported positions.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
