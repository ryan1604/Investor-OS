import { CircleAlert } from 'lucide-react'

type FallbackIndicatorProps = {
  notes: string[]
}

// Marks a value that did not come straight from IB; the notes explain why.
export function FallbackIndicator({ notes }: FallbackIndicatorProps) {
  if (!notes.length) {
    return null
  }

  const description = notes.join(' ')
  return (
    <span
      className="inline-flex align-middle text-amber-500"
      title={description}
      aria-label={description}
      role="img"
    >
      <CircleAlert className="size-3.5" />
    </span>
  )
}
