import type { ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ScreenerFilterDraft } from '@/features/options-screeners/lib/screenerSettings'

export function ScreenerFilterControls({
  action,
  draft,
  error,
  onChange,
  onReset,
  saveStatus,
}: {
  action: ReactNode
  draft: ScreenerFilterDraft
  error: string | null
  onChange: (field: keyof ScreenerFilterDraft, value: string) => void
  onReset: () => void
  saveStatus: 'idle' | 'saving' | 'saved' | 'invalid' | 'error'
}) {
  return (
    <section className="space-y-3" aria-labelledby="filters-heading">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 id="filters-heading" className="text-sm font-semibold">
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
            id="minimum-dte"
            label="Minimum DTE"
            value={draft.minimum_dte}
            onChange={(value) => onChange('minimum_dte', value)}
          />
          <FilterInput
            id="maximum-dte"
            label="Maximum DTE"
            value={draft.maximum_dte}
            onChange={(value) => onChange('maximum_dte', value)}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <FilterInput
            id="minimum-delta"
            label="Minimum delta"
            value={draft.minimum_absolute_delta}
            step="0.01"
            onChange={(value) => onChange('minimum_absolute_delta', value)}
          />
          <FilterInput
            id="maximum-delta"
            label="Maximum delta"
            value={draft.maximum_absolute_delta}
            step="0.01"
            onChange={(value) => onChange('maximum_absolute_delta', value)}
          />
        </div>
        <FilterInput
          id="minimum-return"
          label="Minimum annualized %"
          value={draft.minimum_annualized_return}
          step="0.1"
          onChange={(value) => onChange('minimum_annualized_return', value)}
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
