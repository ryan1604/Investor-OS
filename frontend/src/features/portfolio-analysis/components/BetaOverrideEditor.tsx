import { X } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { BetaOverride } from '@/api/portfolioAnalysis'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { formatNumber } from '@/lib/format'

const MAX_BETA = 10

type BetaOverrideEditorProps = {
  overrides: BetaOverride[]
  tickers: string[]
  isSaving: boolean
  error: string | null
  onSave: (ticker: string, beta: number) => Promise<boolean>
  onRemove: (ticker: string) => Promise<boolean>
}

export function BetaOverrideEditor({
  overrides,
  tickers,
  isSaving,
  error,
  onSave,
  onRemove,
}: BetaOverrideEditorProps) {
  const [ticker, setTicker] = useState('')
  const [beta, setBeta] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedTicker = ticker.trim().toUpperCase()
    const value = Number(beta)
    if (!normalizedTicker) {
      setFormError('Enter a ticker.')
      return
    }
    if (!beta.trim() || !Number.isFinite(value) || Math.abs(value) > MAX_BETA) {
      setFormError(`Enter a beta between -${MAX_BETA} and ${MAX_BETA}.`)
      return
    }
    setFormError(null)
    if (await onSave(normalizedTicker, value)) {
      setTicker('')
      setBeta('')
    }
  }

  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        <h2 className="text-sm font-semibold">Beta Overrides</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          An override replaces the computed 1-year beta to SPY for that ticker.
        </p>
        <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={handleSubmit}>
          <Input
            aria-label="Override ticker"
            className="w-28"
            list="beta-override-tickers"
            placeholder="Ticker"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
          />
          <datalist id="beta-override-tickers">
            {tickers.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
          <Input
            aria-label="Override beta"
            className="w-24"
            inputMode="decimal"
            placeholder="Beta"
            value={beta}
            onChange={(event) => setBeta(event.target.value)}
          />
          <Button type="submit" variant="outline" disabled={isSaving} className="cursor-pointer">
            Save override
          </Button>
        </form>
        {formError || error ? (
          <Alert variant="destructive" className="mt-3">
            {formError ?? error}
          </Alert>
        ) : null}
        {overrides.length ? (
          <ul className="mt-3 flex flex-wrap gap-2 text-xs">
            {overrides.map((override) => (
              <li
                key={override.ticker}
                className="inline-flex items-center gap-1 rounded-md border px-2 py-1"
              >
                <span className="font-medium">{override.ticker}</span>
                <span className="tabular-nums">
                  {formatNumber(override.beta, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${override.ticker} override`}
                  className="cursor-pointer text-muted-foreground hover:text-foreground disabled:cursor-not-allowed"
                  disabled={isSaving}
                  onClick={() => void onRemove(override.ticker)}
                >
                  <X className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  )
}
