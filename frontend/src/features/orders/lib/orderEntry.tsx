import type { ReactNode } from 'react'

import type { OrderPreviewResponse } from '@/api/orders'
import { Field, FieldLabel } from '@/components/ui/field'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export type SelectOption = {
  label: string
  value: string
}

export function SelectField({
  label,
  onValueChange,
  options,
  value,
}: {
  label: string
  onValueChange: (value: string) => void
  options: SelectOption[]
  value: string
}) {
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger aria-label={label} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  )
}

export function ConfirmationPreview({
  children,
  preview,
  summaryLabel,
}: {
  children?: ReactNode
  preview: OrderPreviewResponse
  summaryLabel: string
}) {
  return (
    <div className="grid gap-3 rounded-lg border bg-muted/30 p-3 text-sm">
      <PreviewRow label="Account" value={preview.account} />
      <PreviewRow label={summaryLabel} value={preview.summary} />
      <PreviewRow label="Type" value={preview.estimated_order_type} />
      <PreviewRow label="TIF" value={preview.time_in_force} />
      {children}
    </div>
  )
}

export function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}
