import { useState, type FormEvent } from 'react'

import type { RiskLimit, RiskLimitKey } from '@/api/portfolioAnalysis'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { LIMIT_DEFINITIONS } from '@/features/portfolio-analysis/lib/limits'

type RiskLimitsEditorProps = {
  limits: RiskLimit[]
  isSaving: boolean
  error: string | null
  onSave: (limits: Partial<Record<RiskLimitKey, number>>) => Promise<boolean>
}

function initialValues(limits: RiskLimit[]) {
  // Suggested values pre-fill the form until the account has saved limits.
  return Object.fromEntries(
    LIMIT_DEFINITIONS.map((definition) => {
      const value = limits.length
        ? limits.find((limit) => limit.key === definition.key)?.value
        : definition.suggested
      return [definition.key, value === undefined ? '' : String(value)]
    }),
  ) as Record<RiskLimitKey, string>
}

// Remount (via `key`) when the saved limits change so the form shows them.
export function RiskLimitsEditor({ limits, isSaving, error, onSave }: RiskLimitsEditorProps) {
  const [values, setValues] = useState(() => initialValues(limits))
  const [formError, setFormError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const parsed: Partial<Record<RiskLimitKey, number>> = {}
    for (const definition of LIMIT_DEFINITIONS) {
      const text = values[definition.key].trim()
      if (!text) {
        continue
      }
      const value = Number(text)
      if (!Number.isFinite(value) || value < 0) {
        setFormError(`Enter a number of at least 0 for ${definition.label}, or leave it blank.`)
        return
      }
      parsed[definition.key] = value
    }
    setFormError(null)
    await onSave(parsed)
  }

  return (
    <Card className="mt-6">
      <CardContent className="pt-0">
        <h2 className="text-sm font-semibold">Risk Limits</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {limits.length
            ? 'Saved for this account. Leave a field blank to remove that limit.'
            : 'No limits are set for this account. The suggested values below apply only once saved.'}
        </p>
        <form className="mt-3" onSubmit={handleSubmit}>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {LIMIT_DEFINITIONS.map((definition) => (
              <label key={definition.key} className="flex flex-col gap-1 text-xs">
                <span className="font-medium text-muted-foreground">
                  {definition.label}{' '}
                  <span className="font-normal">
                    ({definition.hint})
                  </span>
                </span>
                <Input
                  aria-label={`${definition.label} limit`}
                  inputMode="decimal"
                  value={values[definition.key]}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [definition.key]: event.target.value }))
                  }
                />
              </label>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <Button type="submit" variant="outline" disabled={isSaving} className="cursor-pointer">
              Save limits
            </Button>
            {limits.length ? (
              <Button
                type="button"
                variant="ghost"
                disabled={isSaving}
                className="cursor-pointer"
                onClick={() => void onSave({})}
              >
                Clear limits
              </Button>
            ) : null}
          </div>
        </form>
        {formError || error ? (
          <Alert variant="destructive" className="mt-3">
            {formError ?? error}
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}
