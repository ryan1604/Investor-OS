import { LoaderCircle } from 'lucide-react'

import type {
  OptionsScreenerCompletedSnapshot,
  OptionsScreenerScanJob,
} from '@/api/optionsScreeners'
import { ScreenerWarnings } from '@/features/options-screeners/components/ScreenerWarnings'

export function ScreenerResultsStatus({
  activeJob,
  snapshot,
  visibleCount,
  headingId,
}: {
  activeJob: OptionsScreenerScanJob | null
  snapshot: OptionsScreenerCompletedSnapshot | null
  visibleCount: number
  headingId: string
}) {
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-lg font-semibold">
            Results
          </h2>
          {snapshot ? (
            <p className="text-xs text-muted-foreground">
              Scanned {formatLocalTimestamp(snapshot.completed_at)}
            </p>
          ) : null}
        </div>
        {snapshot && snapshot.total_match_count > visibleCount ? (
          <p className="text-xs font-medium text-muted-foreground">
            Showing top {visibleCount} of {snapshot.total_match_count} matches
          </p>
        ) : null}
      </div>
      {activeJob ? (
        <div className="space-y-3 rounded-lg border border-blue-500/25 bg-blue-500/5 px-4 py-3">
          <div className="flex items-center gap-2">
            <LoaderCircle className="size-4 animate-spin text-blue-500" />
            <div>
              <p className="text-sm font-semibold">Scan in progress</p>
              <p className="text-xs text-muted-foreground">
                {activeJob.completed_tickers} of {activeJob.total_tickers}{' '}
                tickers scanned
              </p>
            </div>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-blue-600 transition-[width]"
              style={{
                width: `${progressPercent(activeJob.completed_tickers, activeJob.total_tickers)}%`,
              }}
            />
          </div>
        </div>
      ) : (
        <ScreenerWarnings
          errors={snapshot?.errors ?? []}
          warnings={snapshot?.warnings ?? []}
        />
      )}
    </>
  )
}

function progressPercent(completed: number, total: number) {
  return total ? Math.min(100, (completed / total) * 100) : 100
}

function formatLocalTimestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}
