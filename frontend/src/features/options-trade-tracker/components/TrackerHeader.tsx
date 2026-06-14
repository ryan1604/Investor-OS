import { MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'

import type { OptionsTradeTrackerSummary } from '@/api/optionsTradeTrackers'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type TrackerHeaderProps = {
  trackers: OptionsTradeTrackerSummary[]
  selectedTrackerId: string | null
  isLoading: boolean
  onCreate: () => void
  onRename: () => void
  onDelete: () => void
  onSelectTracker: (trackerId: string) => void
}

export function TrackerHeader({
  trackers,
  selectedTrackerId,
  isLoading,
  onCreate,
  onRename,
  onDelete,
  onSelectTracker,
}: TrackerHeaderProps) {
  const hasSelectedTracker = selectedTrackerId !== null

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Options Trade Tracker
        </h1>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Select
          value={selectedTrackerId ?? ''}
          onValueChange={onSelectTracker}
          disabled={trackers.length === 0}
        >
          <SelectTrigger
            aria-label="Select tracker"
            className="h-9 w-full min-w-56 sm:w-64"
          >
            <SelectValue
              placeholder={isLoading ? 'Loading trackers...' : 'No tracker selected'}
            />
          </SelectTrigger>
          <SelectContent>
            {trackers.map((tracker) => (
              <SelectItem key={tracker.id} value={tracker.id}>
                {tracker.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button type="button" onClick={onCreate}>
          <Plus />
          New tracker
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Tracker actions"
              disabled={!hasSelectedTracker}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem onSelect={onRename}>
              <Pencil />
              Rename
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={onDelete}>
              <Trash2 />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
