import { useRef, useState } from 'react'

import type { DraftOptionLeg } from '@/features/options/lib/strategyLegs'

export function useScreenerTicketRefresh<Candidate>({
  refresh,
  errorMessage,
}: {
  refresh: (candidate: Candidate) => Promise<{
    legs: DraftOptionLeg[]
    warning: string | null
  }>
  errorMessage: (error: unknown) => string
}) {
  const [ticketLegs, setTicketLegs] = useState<DraftOptionLeg[]>([])
  const [isTicketOpen, setIsTicketOpen] = useState(false)
  const [ticketError, setTicketError] = useState<string | null>(null)
  const [ticketWarning, setTicketWarning] = useState<string | null>(null)
  const [isRefreshingTicket, setIsRefreshingTicket] = useState(false)
  const refreshSequence = useRef(0)

  async function refreshTicket(candidate: Candidate) {
    const sequence = ++refreshSequence.current
    setTicketError(null)
    setTicketWarning(null)
    setIsRefreshingTicket(true)

    try {
      const ticket = await refresh(candidate)
      if (sequence !== refreshSequence.current) {
        return
      }
      setTicketLegs(ticket.legs)
      setTicketWarning(ticket.warning)
      setIsTicketOpen(true)
    } catch (error) {
      if (sequence === refreshSequence.current) {
        setIsTicketOpen(false)
        setTicketLegs([])
        setTicketError(errorMessage(error))
      }
    } finally {
      if (sequence === refreshSequence.current) {
        setIsRefreshingTicket(false)
      }
    }
  }

  return {
    ticketLegs,
    setTicketLegs,
    isTicketOpen,
    setIsTicketOpen,
    ticketError,
    ticketWarning,
    isRefreshingTicket,
    refreshTicket,
  }
}
