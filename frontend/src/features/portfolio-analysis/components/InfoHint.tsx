import { Info } from 'lucide-react'

type InfoHintProps = {
  note: string
}

// A neutral info marker whose tooltip explains how a figure was estimated.
export function InfoHint({ note }: InfoHintProps) {
  return (
    <span
      className="inline-flex align-middle text-muted-foreground"
      title={note}
      aria-label={note}
      role="img"
    >
      <Info className="size-3.5" />
    </span>
  )
}
