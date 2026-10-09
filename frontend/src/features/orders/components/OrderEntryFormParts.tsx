import type { ReactNode } from 'react'
import { LoaderCircle, Send } from 'lucide-react'

import type { OrderPreviewResponse } from '@/api/orders'
import { Button } from '@/components/ui/button'
import { DialogFooter } from '@/components/ui/dialog'
import { Field, FieldLabel } from '@/components/ui/field'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { TicketStep } from '@/features/orders/hooks/useOrderTicketFlow'

type SelectOption = {
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

export function ReadOnlyTicketAccount({
  account,
  label,
}: {
  account: string
  label: string
}) {
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
        {account || 'No account selected'}
      </div>
    </Field>
  )
}

export function OrderTicketFooter({
  step,
  isSubmitting,
  reviewDisabled,
  onClose,
  onEdit,
  onReview,
  onTransmit,
}: {
  step: TicketStep
  isSubmitting: boolean
  reviewDisabled: boolean
  onClose: () => void
  onEdit: () => void
  onReview: () => void
  onTransmit: () => void
}) {
  return (
    <DialogFooter>
      {step === 'submitted' ? (
        <Button
          type="button"
          onClick={onClose}
          className="cursor-pointer active:cursor-pointer"
        >
          Close
        </Button>
      ) : step === 'confirm' ? (
        <>
          <Button
            type="button"
            variant="outline"
            onClick={onEdit}
            disabled={isSubmitting}
            className="cursor-pointer active:cursor-pointer"
          >
            Edit
          </Button>
          <Button
            type="button"
            onClick={onTransmit}
            disabled={isSubmitting}
            className="cursor-pointer active:cursor-pointer"
          >
            {isSubmitting ? (
              <LoaderCircle className="animate-spin" data-icon="inline-start" />
            ) : (
              <Send data-icon="inline-start" />
            )}
            Transmit
          </Button>
        </>
      ) : (
        <>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            className="cursor-pointer active:cursor-pointer"
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onReview}
            disabled={reviewDisabled || isSubmitting}
            className="cursor-pointer active:cursor-pointer disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <LoaderCircle className="animate-spin" data-icon="inline-start" />
            ) : null}
            Review
          </Button>
        </>
      )}
    </DialogFooter>
  )
}
