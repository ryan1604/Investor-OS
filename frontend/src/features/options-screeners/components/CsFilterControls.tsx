import type { ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'

import type {
  CreditSpreadStrategy,
  CreditSpreadWidth,
} from '@/api/optionsScreeners'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  creditSpreadStrategies,
  creditSpreadWidths,
  type CreditSpreadFilterDraft,
  type ScreenerFilterDraft,
} from '@/features/options-screeners/lib/screenerSettings'

export function CsFilterControls({
  action,
  draft,
  error,
  onChange,
  onReset,
  onToggleStrategy,
  onToggleWidth,
  saveStatus,
}: {
  action: ReactNode
  draft: CreditSpreadFilterDraft
  error: string | null
  onChange: (field: keyof ScreenerFilterDraft, value: string) => void
  onReset: () => void
  onToggleStrategy: (strategy: CreditSpreadStrategy) => void
  onToggleWidth: (width: CreditSpreadWidth) => void
  saveStatus: 'idle' | 'saving' | 'saved' | 'invalid' | 'error'
}) {
  return (
    <section className="space-y-3" aria-labelledby="cs-filters-heading">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 id="cs-filters-heading" className="text-sm font-semibold">
            Filters
          </h2>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="cursor-pointer"
          onClick={onReset}
        >
          <RotateCcw />
          Reset filters
        </Button>
      </div>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <FilterInput
            id="cs-minimum-dte"
            label="Minimum DTE"
            value={draft.minimum_dte}
            onChange={(value) => onChange('minimum_dte', value)}
          />
          <FilterInput
            id="cs-maximum-dte"
            label="Maximum DTE"
            value={draft.maximum_dte}
            onChange={(value) => onChange('maximum_dte', value)}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <FilterInput
            id="cs-minimum-delta"
            label="Minimum short-leg delta"
            value={draft.minimum_absolute_delta}
            step="0.01"
            onChange={(value) => onChange('minimum_absolute_delta', value)}
          />
          <FilterInput
            id="cs-maximum-delta"
            label="Maximum short-leg delta"
            value={draft.maximum_absolute_delta}
            step="0.01"
            onChange={(value) => onChange('maximum_absolute_delta', value)}
          />
        </div>
        <FilterInput
          id="cs-minimum-return"
          label="Minimum annualized %"
          value={draft.minimum_annualized_return}
          step="0.1"
          onChange={(value) => onChange('minimum_annualized_return', value)}
        />
        <SelectionGroup
          label="Strategy"
          options={creditSpreadStrategies}
          selected={draft.strategy_types}
          onToggle={onToggleStrategy}
        />
        <SelectionGroup
          label="Width"
          options={creditSpreadWidths}
          selected={draft.spread_widths}
          onToggle={onToggleWidth}
        />
      </div>
      <div className="flex min-h-9 flex-wrap items-center justify-between gap-3 text-xs">
        <div>
          {error ? (
            <p className="text-destructive">{error}</p>
          ) : saveStatus === 'saving' ? (
            <p className="text-muted-foreground">Saving filters...</p>
          ) : saveStatus === 'error' ? (
            <p className="text-destructive">
              Filters are unsaved. The last valid backend values are unchanged.
            </p>
          ) : saveStatus === 'saved' ? (
            <p className="text-muted-foreground">Filters saved.</p>
          ) : (
            <p className="text-muted-foreground">Unsaved changes.</p>
          )}
        </div>
        <div className="ml-auto">{action}</div>
      </div>
    </section>
  )
}

function SelectionGroup<Value extends string | number>({
  label,
  onToggle,
  options,
  selected,
}: {
  label: string
  onToggle: (value: Value) => void
  options: { value: Value; label: string }[]
  selected: Value[]
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const checked = selected.includes(option.value)
          return (
            <Badge
              key={String(option.value)}
              variant={checked ? 'default' : 'outline'}
              className="h-8 gap-2 rounded-md px-2.5"
            >
              <Checkbox
                aria-label={option.label}
                checked={checked}
                onCheckedChange={() => onToggle(option.value)}
              />
              <button
                type="button"
                className="cursor-pointer"
                onClick={() => onToggle(option.value)}
              >
                {option.label}
              </button>
            </Badge>
          )
        })}
      </div>
    </div>
  )
}

function FilterInput({
  id,
  label,
  onChange,
  step = '1',
  value,
}: {
  id: string
  label: string
  onChange: (value: string) => void
  step?: string
  value: string
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Input
        className="[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        id={id}
        type="number"
        inputMode="decimal"
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}
