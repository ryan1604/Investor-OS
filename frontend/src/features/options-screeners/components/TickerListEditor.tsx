import { type ReactNode, useState } from 'react'
import { Plus, X } from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { parseUncheckedScreenerTickers } from '@/features/options-screeners/lib/screenerSettings'

export function TickerListEditor({
  clearActionLabel = 'Clear shared list',
  clearDescription = (
    <>
      This removes every saved ticker from both the CSP and covered-call
      screeners. Completed scan snapshots are not changed.
    </>
  ),
  clearTitle = 'Clear the shared CSP / CC list?',
  error,
  isPending,
  onAdd,
  onClear,
  onRemove,
  tickers,
}: {
  clearActionLabel?: string
  clearDescription?: ReactNode
  clearTitle?: string
  error: string | null
  isPending: boolean
  onAdd: (tickers: string[]) => Promise<void>
  onClear: () => Promise<void>
  onRemove: (ticker: string) => Promise<void>
  tickers: string[]
}) {
  const [input, setInput] = useState('')

  async function submit() {
    const parsed = parseUncheckedScreenerTickers(input)
    if (!parsed.length) {
      return
    }
    await onAdd(parsed)
    setInput('')
  }

  return (
    <section className="space-y-3" aria-labelledby="ticker-list-heading">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 id="ticker-list-heading" className="text-sm font-semibold">
            Ticker
          </h2>
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="cursor-pointer disabled:cursor-not-allowed"
              disabled={!tickers.length || isPending}
            >
              Clear all
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{clearTitle}</AlertDialogTitle>
              <AlertDialogDescription>
                {clearDescription}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep tickers</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                onClick={() => void onClear()}
              >
                {clearActionLabel}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      <div className="flex gap-2">
        <Textarea
          aria-label="Add ticker symbols"
          value={input}
          rows={1}
          className="h-10 min-h-10 resize-none py-2 font-mono text-sm uppercase"
          placeholder="AAPL"
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void submit()
            }
          }}
        />
        <Button
          className="h-10 shrink-0 cursor-pointer disabled:cursor-not-allowed"
          disabled={!parseUncheckedScreenerTickers(input).length || isPending}
          onClick={() => void submit()}
        >
          <Plus />
          Add
        </Button>
      </div>

      <div className="max-h-32 min-h-12 overflow-y-auto rounded-lg border bg-muted/25 p-2">
        {tickers.length ? (
          <div className="flex flex-wrap gap-2">
            {tickers.map((ticker) => (
              <Badge
                key={ticker}
                className="gap-1.5 border border-blue-400/25 bg-blue-500/15 py-1 font-mono text-blue-200 hover:bg-blue-500/20"
              >
                {ticker}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Remove ${ticker}`}
                  className="-mr-1 size-4 cursor-pointer rounded-sm p-0 opacity-60 hover:bg-transparent hover:opacity-100"
                  disabled={isPending}
                  onClick={() => void onRemove(ticker)}
                >
                  <X className="size-3" />
                </Button>
              </Badge>
            ))}
          </div>
        ) : (
          <p className="px-1 py-1 text-sm text-muted-foreground">
            No saved tickers. Add at least one ticker to scan.
          </p>
        )}
      </div>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </section>
  )
}
