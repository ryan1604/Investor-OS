import { LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import type {
  OptionsScreenerCompletedSnapshot,
  OptionsScreenerScanJob,
} from '@/api/optionsScreeners'
import { Alert } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { ScreenerResultsStatus } from '@/features/options-screeners/components/ScreenerResultsStatus'

export function ScreenerPageShell({
  title,
  loadError,
  scanActionError,
  tickerEditor,
  filters,
  headingId,
  activeJob,
  snapshot,
  visibleCount,
  ticketError,
  isRefreshingTicket,
  refreshMessage,
  results,
  children,
}: {
  title: string
  loadError: string | null
  scanActionError: string | null
  tickerEditor: ReactNode
  filters: ReactNode
  headingId: string
  activeJob: OptionsScreenerScanJob | null
  snapshot: OptionsScreenerCompletedSnapshot | null
  visibleCount: number
  ticketError: string | null
  isRefreshingTicket: boolean
  refreshMessage: string
  results: ReactNode
  children: ReactNode
}) {
  return (
    <main className="w-full space-y-5">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
      </header>

      {loadError ? <Alert variant="destructive">{loadError}</Alert> : null}
      {scanActionError ? (
        <Alert variant="destructive">{scanActionError}</Alert>
      ) : null}
      <Card className="pt-2">
        <CardContent className="space-y-6">
          {tickerEditor}
          {filters}
        </CardContent>
      </Card>

      <section className="space-y-3" aria-labelledby={headingId}>
        <ScreenerResultsStatus
          activeJob={activeJob}
          snapshot={snapshot}
          visibleCount={visibleCount}
          headingId={headingId}
        />
        {ticketError ? <Alert variant="destructive">{ticketError}</Alert> : null}
        {isRefreshingTicket ? (
          <Alert className="flex items-center gap-2">
            <LoaderCircle className="size-4 shrink-0 animate-spin" />
            <span>{refreshMessage}</span>
          </Alert>
        ) : null}
        {results}
      </section>
      {children}
    </main>
  )
}
