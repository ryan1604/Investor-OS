import { useMemo, useState } from 'react'
import { FileSpreadsheet, Loader2, Plus } from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { MonthlyPerformanceChart } from '@/features/options-trade-tracker/components/MonthlyPerformanceChart'
import { StatsSummaryTable } from '@/features/options-trade-tracker/components/StatsSummaryTable'
import { StrategyExecutionPieChart } from '@/features/options-trade-tracker/components/StrategyExecutionPieChart'
import { TrackerHeader } from '@/features/options-trade-tracker/components/TrackerHeader'
import { TrackerNotes } from '@/features/options-trade-tracker/components/TrackerNotes'
import { TradesTable } from '@/features/options-trade-tracker/components/TradesTable'
import { useOptionsTradeTracker } from '@/features/options-trade-tracker/hooks/useOptionsTradeTracker'
import {
  deriveStrategyStats,
  projectCompletedValidTrades,
  storedRowFromTradeDraft,
  type TradeDraftField,
  type TradeDraftRow,
  type TradeDraftValidationIssue,
} from '@/features/options-trade-tracker/lib/tradeTracker'

type TrackerDialogMode = 'create' | 'rename'
type TrackerTab = 'trades' | 'stats'

export function OptionsTradeTrackerPage() {
  const tracker = useOptionsTradeTracker()
  const [activeTab, setActiveTab] = useState<TrackerTab>('trades')
  const [dialogMode, setDialogMode] = useState<TrackerDialogMode | null>(null)
  const [trackerName, setTrackerName] = useState('')
  const [isStrategyDialogOpen, setIsStrategyDialogOpen] = useState(false)
  const [strategyName, setStrategyName] = useState('')
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)

  function openCreateDialog() {
    tracker.setSaveError(null)
    setTrackerName('')
    setDialogMode('create')
  }

  function openRenameDialog() {
    if (tracker.selectedTracker === null) {
      return
    }

    tracker.setSaveError(null)
    setTrackerName(tracker.selectedTracker.name)
    setDialogMode('rename')
  }

  async function submitTrackerDialog() {
    const normalizedName = trackerName.trim()

    if (!normalizedName) {
      tracker.setSaveError('Tracker name is required.')
      return
    }

    const didSave =
      dialogMode === 'create'
        ? await tracker.createTracker(normalizedName)
        : await tracker.renameSelectedTracker(normalizedName)
    if (didSave) {
      setDialogMode(null)
      setTrackerName('')
    }
  }

  async function confirmDeleteTracker() {
    if (await tracker.deleteSelectedTracker()) {
      setIsDeleteOpen(false)
    }
  }

  async function submitStrategyDialog() {
    const didCreate = await tracker.createStrategyOption(strategyName)
    if (didCreate) {
      setStrategyName('')
      setIsStrategyDialogOpen(false)
    }
  }

  return (
    <main className="flex w-full flex-col gap-5">
      <TrackerHeader
        trackers={tracker.trackers}
        selectedTrackerId={tracker.selectedTrackerId}
        isLoading={tracker.isInitialLoading}
        onCreate={openCreateDialog}
        onRename={openRenameDialog}
        onDelete={() => setIsDeleteOpen(true)}
        onSelectTracker={tracker.selectTracker}
      />

      <StatusStrip
        isInitialLoading={tracker.isInitialLoading}
        isDetailLoading={tracker.isDetailLoading}
        loadError={tracker.loadError}
        saveError={tracker.saveError}
      />

      {tracker.trackers.length === 0 && !tracker.isInitialLoading ? (
        <EmptyTrackerState onCreate={openCreateDialog} />
      ) : tracker.selectedTrackerId === null ? (
        <NoSelectionState trackerCount={tracker.trackers.length} />
      ) : tracker.detailTrackerId !== tracker.selectedTrackerId ? (
        <TrackerDetailLoadingState />
      ) : (
        <TrackerWorkspace
          activeTab={activeTab}
          isLoading={tracker.isDetailLoading}
          isSavingNotes={tracker.isSavingNotes}
          isSavingTrades={tracker.isSavingTrades}
          notes={tracker.notesDraft}
          strategyOptions={tracker.strategyOptions}
          tradeIssues={tracker.tradeIssues}
          tradeRows={tracker.tradeRows}
          onAddTradeRow={tracker.addTradeRow}
          onDeleteTradeRow={tracker.deleteTradeRow}
          onOpenStrategyDialog={() => {
            tracker.setSaveError(null)
            setStrategyName('')
            setIsStrategyDialogOpen(true)
          }}
          onReorderTradeRow={tracker.reorderTradeRow}
          onNotesChange={tracker.updateNotesDraft}
          onSaveNotes={tracker.saveNotes}
          onSaveTrades={tracker.saveTradeRows}
          onTabChange={setActiveTab}
          onUpdateTradeRow={tracker.updateTradeRow}
        />
      )}

      <TrackerNameDialog
        mode={dialogMode}
        name={trackerName}
        error={tracker.saveError}
        isSaving={tracker.isCreating || tracker.isSavingMetadata}
        onNameChange={setTrackerName}
        onOpenChange={(open) => {
          if (!open) {
            setDialogMode(null)
          }
        }}
        onSubmit={submitTrackerDialog}
      />

      <StrategyNameDialog
        name={strategyName}
        error={tracker.saveError}
        isOpen={isStrategyDialogOpen}
        isSaving={tracker.isSavingStrategies}
        onNameChange={setStrategyName}
        onOpenChange={(open) => {
          setIsStrategyDialogOpen(open)
          if (!open) {
            setStrategyName('')
          }
        }}
        onSubmit={submitStrategyDialog}
      />

      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent
          onOverlayPointerDown={() => setIsDeleteOpen(false)}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Delete tracker?</AlertDialogTitle>
            <AlertDialogDescription className="text-wrap">
              This removes the selected tracker, including its trades and notes.
              Global strategy options stay available.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="border-t-0 bg-popover">
            <AlertDialogCancel disabled={tracker.isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={tracker.isDeleting}
              onClick={(event) => {
                event.preventDefault()
                void confirmDeleteTracker()
              }}
            >
              Delete tracker
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  )
}

function TrackerDetailLoadingState() {
  return (
    <section
      className="flex min-h-[460px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground"
      role="status"
    >
      Loading selected tracker...
    </section>
  )
}

function StatusStrip({
  isInitialLoading,
  isDetailLoading,
  loadError,
  saveError,
}: {
  isInitialLoading: boolean
  isDetailLoading: boolean
  loadError: string | null
  saveError: string | null
}) {
  if (loadError !== null) {
    return <Alert variant="destructive">{loadError}</Alert>
  }

  if (saveError !== null) {
    return <Alert variant="destructive">{saveError}</Alert>
  }

  if (isInitialLoading || isDetailLoading) {
    return (
      <div
        className="flex items-center gap-2 text-sm text-muted-foreground"
        role="status"
      >
        <Loader2 className="size-4 animate-spin" />
        {isInitialLoading ? 'Loading trackers...' : 'Loading tracker...'}
      </div>
    )
  }

  return null
}

function EmptyTrackerState({ onCreate }: { onCreate: () => void }) {
  return (
    <section className="flex min-h-[420px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-4">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-lg bg-background ring-1 ring-border">
          <FileSpreadsheet className="size-6 text-muted-foreground" />
        </div>
        <h2 className="text-lg font-semibold text-foreground">
          No trackers yet
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Create a named workspace before adding trades, notes, and stats.
        </p>
        <Button type="button" className="mt-5" onClick={onCreate}>
          <Plus />
          Create tracker
        </Button>
      </div>
    </section>
  )
}

function NoSelectionState({ trackerCount }: { trackerCount: number }) {
  return (
    <section className="rounded-lg border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
      {trackerCount} tracker{trackerCount === 1 ? '' : 's'} available. Select
      one to open its Trades and Stats workspace.
    </section>
  )
}

function TrackerWorkspace({
  activeTab,
  isLoading,
  isSavingNotes,
  isSavingTrades,
  notes,
  strategyOptions,
  tradeIssues,
  tradeRows,
  onAddTradeRow,
  onDeleteTradeRow,
  onOpenStrategyDialog,
  onReorderTradeRow,
  onNotesChange,
  onSaveNotes,
  onSaveTrades,
  onTabChange,
  onUpdateTradeRow,
}: {
  activeTab: TrackerTab
  isLoading: boolean
  isSavingNotes: boolean
  isSavingTrades: boolean
  notes: string
  strategyOptions: string[]
  tradeIssues: TradeDraftValidationIssue[]
  tradeRows: TradeDraftRow[]
  onAddTradeRow: () => void
  onDeleteTradeRow: (localId: string) => void
  onOpenStrategyDialog: () => void
  onReorderTradeRow: (draggedLocalId: string, targetLocalId: string) => void
  onNotesChange: (notes: string) => void
  onSaveNotes: () => void
  onSaveTrades: () => void
  onTabChange: (tab: TrackerTab) => void
  onUpdateTradeRow: (
    localId: string,
    field: TradeDraftField,
    value: string,
  ) => void
}) {
  const storedRows = useMemo(
    () => tradeRows.map((row, index) => storedRowFromTradeDraft(row, index + 1)),
    [tradeRows],
  )
  const completedTrades = useMemo(
    () => projectCompletedValidTrades(storedRows),
    [storedRows],
  )
  const strategyStats = useMemo(
    () => deriveStrategyStats(completedTrades, strategyOptions),
    [completedTrades, strategyOptions],
  )

  return (
    <section className="flex min-h-[460px] flex-col gap-4">
      <Tabs
        value={activeTab}
        onValueChange={(value) => onTabChange(value as TrackerTab)}
      >
        <TabsList>
          <TabsTrigger value="trades" onClick={() => onTabChange('trades')}>
            Trades
          </TabsTrigger>
          <TabsTrigger value="stats" onClick={() => onTabChange('stats')}>
            Stats
          </TabsTrigger>
        </TabsList>
        <TabsContent value="trades">
          <div className="grid gap-4">
            <TradesTable
              rows={tradeRows}
              completedTrades={completedTrades}
              strategies={strategyOptions}
              issues={tradeIssues}
              isSaving={isSavingTrades || isLoading}
              onAddRow={onAddTradeRow}
              onDeleteRow={onDeleteTradeRow}
              onOpenStrategyDialog={onOpenStrategyDialog}
              onReorderRow={onReorderTradeRow}
              onSave={onSaveTrades}
              onUpdateRow={onUpdateTradeRow}
            />
            <TrackerNotes
              notes={notes}
              isSaving={isSavingNotes || isLoading}
              onChange={onNotesChange}
              onSave={onSaveNotes}
            />
          </div>
        </TabsContent>
        <TabsContent value="stats">
          <div className="grid gap-4">
            <StatsSummaryTable stats={strategyStats} />
            <MonthlyPerformanceChart
              completedTrades={completedTrades}
              strategyOptions={strategyOptions}
            />
            <StrategyExecutionPieChart completedTrades={completedTrades} />
          </div>
        </TabsContent>
      </Tabs>
    </section>
  )
}

function TrackerNameDialog({
  mode,
  name,
  error,
  isSaving,
  onNameChange,
  onOpenChange,
  onSubmit,
}: {
  mode: TrackerDialogMode | null
  name: string
  error: string | null
  isSaving: boolean
  onNameChange: (name: string) => void
  onOpenChange: (open: boolean) => void
  onSubmit: () => void
}) {
  const isOpen = mode !== null

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {mode === 'rename' ? 'Rename tracker' : 'Create tracker'}
          </DialogTitle>
          <DialogDescription>
            Tracker names must be unique across your saved options workspaces.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void onSubmit()
          }}
        >
          <Input
            autoFocus
            aria-label="Tracker name"
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="June income trades"
          />
          {error !== null ? (
            <div className="text-sm text-destructive">{error}</div>
          ) : null}
          <DialogFooter>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving...' : mode === 'rename' ? 'Rename' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function StrategyNameDialog({
  name,
  error,
  isOpen,
  isSaving,
  onNameChange,
  onOpenChange,
  onSubmit,
}: {
  name: string
  error: string | null
  isOpen: boolean
  isSaving: boolean
  onNameChange: (name: string) => void
  onOpenChange: (open: boolean) => void
  onSubmit: () => void
}) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add strategy</DialogTitle>
          <DialogDescription>
            Strategy names are shared across options trade trackers.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void onSubmit()
          }}
        >
          <Input
            autoFocus
            aria-label="Strategy name"
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="IRON CONDOR"
          />
          {error !== null ? (
            <div className="text-sm text-destructive">{error}</div>
          ) : null}
          <DialogFooter>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Add strategy'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
