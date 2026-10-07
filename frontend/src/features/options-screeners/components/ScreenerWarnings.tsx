import { useState } from 'react'
import { CircleAlert, ChevronDown, Info } from 'lucide-react'

import type {
  OptionsScreenerScanJob,
  OptionsScreenerTickerWarning,
} from '@/api/optionsScreeners'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'

export function ScreenerWarnings({
  errors,
  warnings,
}: {
  errors: OptionsScreenerScanJob['errors']
  warnings: OptionsScreenerTickerWarning[]
}) {
  const [open, setOpen] = useState(false)
  const noMatches = warnings.filter((warning) => warning.category === 'no_matches')
  const excluded = warnings.filter(
    (warning) =>
      warning.category === 'excluded_contracts' ||
      warning.category === 'line_limit',
  )
  if (!errors.length && !warnings.length) {
    return null
  }
  const excludedCount = excluded.reduce(
    (total, warning) => total + warning.count,
    0,
  )
  const hasFailures = errors.length > 0
  const SummaryIcon = hasFailures ? CircleAlert : Info

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div
        className={
          hasFailures
            ? 'rounded-lg border border-red-500/25 bg-red-500/5'
            : 'rounded-lg border border-blue-500/25 bg-blue-500/5'
        }
      >
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="h-auto w-full justify-between rounded-lg px-3 py-2 text-left"
          >
            <span className="flex items-center gap-2 text-xs">
              <SummaryIcon
                className={`size-3.5 ${hasFailures ? 'text-red-500' : 'text-blue-500'}`}
              />
              {errors.length} failed ticker{errors.length === 1 ? '' : 's'}
              {' · '}
              {noMatches.length} with no matches
              {' · '}
              {excludedCount} excluded contract{excludedCount === 1 ? '' : 's'}
            </span>
            <ChevronDown
              className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`}
            />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t px-4 py-3">
          <div className="grid gap-4 text-xs md:grid-cols-3">
            <WarningGroup title="Failed tickers" items={errors} />
            <WarningGroup
              title="No matches"
              items={noMatches.map(
                (warning) => `${warning.ticker}: ${warning.message}`,
              )}
            />
            <WarningGroup
              title="Excluded data"
              items={excluded.map(
                (warning) =>
                  `${warning.ticker}: ${warning.count} contract${warning.count === 1 ? '' : 's'}${warning.category === 'line_limit' ? ' (line limit)' : ''}`,
              )}
            />
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

function WarningGroup({ items, title }: { items: string[]; title: string }) {
  return (
    <div>
      <p className="mb-1 font-semibold">{title}</p>
      {items.length ? (
        <ul className="space-y-1 text-muted-foreground">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">None</p>
      )}
    </div>
  )
}
