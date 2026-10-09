import { useState } from 'react'

import { Input } from '@/components/ui/input'

export function NumberCell({
  label,
  value,
  formatValue,
  className = 'w-full text-right tabular-nums',
  onChange,
}: {
  label: string
  value: string
  formatValue?: (value: string) => string
  className?: string
  onChange: (value: string) => void
}) {
  const [isFocused, setIsFocused] = useState(false)
  const displayValue = formatValue && !isFocused ? formatValue(value) : value

  return (
    <Input
      aria-label={label}
      className={className}
      inputMode="decimal"
      value={displayValue}
      onFocus={() => setIsFocused(true)}
      onBlur={() => setIsFocused(false)}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

export function FieldIssue({
  issues,
  localId,
  field,
  className = 'mt-1 max-w-44 whitespace-normal text-xs text-destructive',
}: {
  issues: readonly { localId: string; field: string; message: string }[]
  localId: string
  field: string
  className?: string
}) {
  const issue = issues.find(
    (candidate) => candidate.localId === localId && candidate.field === field,
  )

  return issue ? <div className={className}>{issue.message}</div> : null
}
