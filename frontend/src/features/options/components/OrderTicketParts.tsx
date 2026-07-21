import { LoaderCircle, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import { SheetFooter } from '@/components/ui/sheet'
import type { TicketStep } from '@/features/orders/lib/orderTicketFlow'

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
    <SheetFooter>
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
    </SheetFooter>
  )
}
