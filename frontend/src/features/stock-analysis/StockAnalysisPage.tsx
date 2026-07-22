import { useState } from 'react'

import { Search, Trash2 } from 'lucide-react'

import { Alert } from '@/components/ui/alert'
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
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  ScenarioValuationTable,
} from '@/features/stock-analysis/components/ScenarioValuationTable'
import {
  normalizeTickerInput,
  useStockAnalysisModel,
  type SaveStatus,
} from '@/features/stock-analysis/hooks/useStockAnalysisModel'
import { formatValuationValue } from '@/features/stock-analysis/lib/valuationFormatting'
import { SCENARIO_KEYS } from '@/features/stock-analysis/lib/valuationModel'

export function StockAnalysisPage() {
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const {
    activeModel,
    calculatedModel,
    commitCellDraft,
    currentPriceStatus,
    deleteActiveModel,
    editingCell,
    error,
    firstForecastYearInput,
    handleTickerSubmit,
    isDeleting,
    saveStatus,
    setEditingCell,
    setTickerSearch,
    tickerSearch,
    updateFirstForecastYear,
  } = useStockAnalysisModel()

  async function confirmDeleteModel() {
    if (await deleteActiveModel()) {
      setIsDeleteOpen(false)
    }
  }

  return (
    <main className="flex min-w-0 w-full flex-col gap-6">
      <div className="flex flex-col gap-2">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">
            Ticker
          </h1>

          <form
            className="flex min-w-0 items-center gap-2 sm:max-w-sm"
            onSubmit={handleTickerSubmit}
          >
            <Input
              aria-label="Ticker"
              autoCapitalize="characters"
              autoComplete="off"
              className="h-9 uppercase"
              disabled={saveStatus === 'loading'}
              maxLength={12}
              placeholder="AAPL"
              value={tickerSearch}
              onChange={(event) =>
                setTickerSearch(normalizeTickerInput(event.target.value))
              }
            />
            <Button
              className="cursor-pointer active:cursor-pointer"
              disabled={saveStatus === 'loading'}
              type="submit"
            >
              <Search data-icon="inline-start" />
              Search
            </Button>
          </form>
        </header>
        <p className="text-sm text-muted-foreground">
          Search a ticker to start a manual stock valuation workspace.
        </p>
      </div>

      {error ? <Alert variant="destructive">{error}</Alert> : null}

      {activeModel ? (
        <section className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <h2 className="text-xl font-semibold tracking-tight">
                {activeModel.ticker} valuation model
              </h2>
              <SaveStatusBadge status={saveStatus} />
              <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
                <AlertDialogTrigger asChild>
                  <Button
                    aria-label={`Delete ${activeModel.ticker} valuation model`}
                    className="cursor-pointer active:cursor-pointer"
                    disabled={isDeleting}
                    size="icon-sm"
                    type="button"
                    variant="destructive"
                  >
                    <Trash2 />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      Delete {activeModel.ticker} valuation model?
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      This permanently removes the saved model and current price
                      snapshot for this ticker.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter className="border-t-0 bg-popover">
                    <AlertDialogCancel disabled={isDeleting}>
                      Keep model
                    </AlertDialogCancel>
                    <AlertDialogAction
                      disabled={isDeleting}
                      variant="destructive"
                      onClick={(event) => {
                        event.preventDefault()
                        void confirmDeleteModel()
                      }}
                    >
                      Delete model
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5 text-sm">
                <div className="font-medium text-foreground">Current price</div>
                <div
                  aria-label="Current price"
                  className="flex h-8 items-center rounded-lg border bg-muted/20 px-2.5 text-sm tabular-nums text-muted-foreground"
                >
                  {currentPriceStatus === 'loading'
                    ? 'Loading...'
                    : activeModel.valuation.currentPrice === null
                      ? 'Unavailable'
                      : formatValuationValue(
                          'sharePriceEstimateLow',
                          activeModel.valuation.currentPrice,
                        )}
                </div>
              </div>
              <Field className="w-full sm:w-56">
                <FieldLabel htmlFor="first-forecast-year">
                  First forecast year
                </FieldLabel>
                <Input
                  aria-label="First forecast year"
                  id="first-forecast-year"
                  inputMode="numeric"
                  maxLength={4}
                  placeholder="2027"
                  value={firstForecastYearInput}
                  onChange={(event) => updateFirstForecastYear(event.target.value)}
                />
              </Field>
            </div>
          </div>

          <div className="grid min-w-0 gap-6">
            {SCENARIO_KEYS.map((scenario) => (
              <ScenarioValuationTable
                calculatedScenario={calculatedModel.scenarios[scenario]}
                key={scenario}
                scenario={scenario}
                yearHeaders={calculatedModel.yearHeaders}
                editingCell={editingCell}
                onCellCommit={commitCellDraft}
                onEditingCellChange={setEditingCell}
              />
            ))}
          </div>
        </section>
      ) : null}
    </main>
  )
}

function SaveStatusBadge({ status }: { status: SaveStatus }) {
  if (status === 'idle') {
    return null
  }

  if (status === 'error') {
    return <Badge variant="destructive">Unsaved changes</Badge>
  }

  if (status === 'saving' || status === 'loading') {
    return <Badge variant="secondary">Saving...</Badge>
  }

  if (status === 'unsaved') {
    return <Badge variant="outline">Unsaved changes</Badge>
  }

  return <Badge variant="secondary">Saved</Badge>
}
