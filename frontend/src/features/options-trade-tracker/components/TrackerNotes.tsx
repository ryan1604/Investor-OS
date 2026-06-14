import { Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

type TrackerNotesProps = {
  notes: string
  isSaving: boolean
  onChange: (notes: string) => void
  onSave: () => void
}

export function TrackerNotes({
  notes,
  isSaving,
  onChange,
  onSave,
}: TrackerNotesProps) {
  return (
    <section className="grid gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="font-medium text-foreground">Notes</h3>
        <Button type="button" variant="outline" onClick={onSave} disabled={isSaving}>
          <Save />
          {isSaving ? 'Saving...' : 'Save notes'}
        </Button>
      </div>
      <Textarea
        aria-label="Tracker notes"
        className="min-h-28 resize-y"
        value={notes}
        onChange={(event) => onChange(event.target.value)}
      />
    </section>
  )
}
