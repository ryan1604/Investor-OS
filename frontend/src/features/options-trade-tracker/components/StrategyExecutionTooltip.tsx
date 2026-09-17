import { useState, type ComponentProps } from 'react'

import { ChartTooltipContent } from '@/components/ui/chart'
import type { StrategyCountPieSlice } from '@/features/options-trade-tracker/lib/tradeTracker'
import { formatNumber } from '@/lib/format'

type TooltipContentProps = ComponentProps<typeof ChartTooltipContent>
type StrategyExecutionTooltipProps = Pick<TooltipContentProps, 'active' | 'payload' | 'label'> & {
  data: readonly (StrategyCountPieSlice & { strategyKey: string })[]
}
type RetainedContent = Pick<StrategyExecutionTooltipProps, 'data' | 'payload' | 'label'>

export function StrategyExecutionTooltip({ active, payload, label, data }: StrategyExecutionTooltipProps) {
  const [retained, setRetained] = useState<RetainedContent | null>(null)
  let content = retained?.data === data && data.length > 0 ? retained : null

  if (active) {
    // Recharts can briefly supply the previous payload while registering new data.
    const item = payload?.length === 1 ? payload[0] : undefined
    const valid = item && data.some((slice) =>
      slice.strategyKey === item.payload?.strategyKey &&
      slice.strategy === item.name &&
      slice.count === item.value &&
      Number.isFinite(slice.count) && slice.count > 0,
    )
    content = valid ? { data, payload, label } : null
  }

  // Update during render so a data change cannot commit the old cached content.
  if (content?.data !== retained?.data || content?.payload !== retained?.payload || content?.label !== retained?.label) {
    setRetained(content)
  }

  if (!content) return null

  // Only the inner content stays rendered. Recharts still owns the outer
  // wrapper's visibility, position, Escape handling, and reduced-motion behavior.
  return (
    <ChartTooltipContent
      active
      payload={content.payload}
      label={content.label}
      hideLabel
      nameKey="strategyKey"
      valueFormatter={(value) => formatNumber(Number(value))}
    />
  )
}
