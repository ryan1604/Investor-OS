import { useState } from 'react'

import {
  previewOrder,
  transmitOrder,
  type OrderPreviewableRequest,
  type OrderPreviewResponse,
} from '@/api/orders'
import { toast } from 'sonner'

export type TicketStep = 'draft' | 'confirm' | 'submitted'

export function useOrderTicketFlow(errorMessage: (error: unknown) => string) {
  const [step, setStep] = useState<TicketStep>('draft')
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function resetTicketState() {
    setStep('draft')
    setPreview(null)
    setError(null)
    setIsSubmitting(false)
  }

  async function review(request: OrderPreviewableRequest | null) {
    if (!request) {
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      setPreview(await previewOrder(request))
      setStep('confirm')
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function transmit() {
    if (!preview) {
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      const response = await transmitOrder(preview.request)
      toast.success(response.message)
      setStep('submitted')
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return {
    step,
    setStep,
    preview,
    error,
    isSubmitting,
    setError,
    resetTicketState,
    review,
    transmit,
  }
}
