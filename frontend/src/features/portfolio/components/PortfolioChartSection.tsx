import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { Pencil } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { formatCompactCurrency, formatOptionalCurrency } from '@/lib/format'
import type {
  PortfolioChartValue,
  PortfolioChartValueRequest,
} from '@/api/portfolioChartValues'
import { errorMessage } from '@/lib/errors'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  PortfolioChartValuesEditor,
} from '@/features/portfolio/components/PortfolioChartValuesEditor'
import {
  normalizePortfolioChartValues,
  parsePortfolioChartValueDraftRows,
  type PortfolioChartValueDraftRow,
  type PortfolioChartValueInput,
  type PortfolioChartMetricKey,
  type PortfolioMonthlyChartRow,
} from '@/features/portfolio/lib/chartValues'


type PortfolioChartSectionProps = {
  account: string | undefined
  currency?: string
  error: string | null
  isLoading: boolean
  isSaving: boolean
  onSaveRows: (rows: PortfolioChartValueRequest[]) => Promise<PortfolioChartValue[]>
  rows: PortfolioChartValue[]
}

const chartConfig = {
  amount_invested: {
    label: 'Amount invested',
    color: 'var(--chart-amount-invested)',
  },
} satisfies ChartConfig

export function PortfolioChartSection({
  account,
  currency = 'USD',
  error,
  isLoading,
  isSaving,
  onSaveRows,
  rows,
}: PortfolioChartSectionProps) {
  const [isEditorOpen, setIsEditorOpen] = useState(false)
  const [draftRows, setDraftRows] = useState<PortfolioChartValueDraftRow[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const accountRef = useRef(account)
  const initialized = useRef(false)
  const previewRows = useMemo(
    () => editorPreviewRows(isEditorOpen, draftRows, rows),
    [isEditorOpen, draftRows, rows],
  )
  const monthlyRows = useMemo(
    () => normalizePortfolioChartValues(previewRows),
    [previewRows],
  )
  const hasSavedValues = monthlyRows.length > 0

  useEffect(() => {
    accountRef.current = account
    if (!initialized.current) {
      initialized.current = true
      return
    }
    Promise.resolve().then(() => {
      setIsEditorOpen(false)
      setDraftRows(savedRowsToDraftRows(rows))
      setSaveError(null)
    })
  }, [account, rows])

  const handleEditorOpenChange = (open: boolean) => {
    setIsEditorOpen(open)
    setSaveError(null)

    if (open) {
      setDraftRows(savedRowsToDraftRows(rows))
    }
  }

  const handleChangeDraftRow = (
    index: number,
    field: keyof PortfolioChartValueDraftRow,
    value: string,
  ) => {
    setDraftRows((currentRows) =>
      currentRows.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [field]: value } : row,
      ),
    )
  }

  const handleAddDraftRow = () => {
    setDraftRows((currentRows) => [
      ...currentRows,
      { month: '', amount_invested: '' },
    ])
  }

  const handleDeleteDraftRow = (index: number) => {
    setDraftRows((currentRows) =>
      currentRows.filter((_, rowIndex) => rowIndex !== index),
    )
  }

  const handleCancel = () => {
    setDraftRows(savedRowsToDraftRows(rows))
    setSaveError(null)
    setIsEditorOpen(false)
  }

  const handleSave = async () => {
    const saveAccount = account

    try {
      const nextRows = parsePortfolioChartValueDraftRows(draftRows)
      const savedRows = await onSaveRows(nextRows)
      if (accountRef.current !== saveAccount) {
        return
      }

      setDraftRows(savedRowsToDraftRows(savedRows))
      setSaveError(null)
      setIsEditorOpen(false)
    } catch (saveError) {
      if (accountRef.current !== saveAccount) {
        return
      }

      setSaveError(errorMessage(saveError, 'Save failed.'))
    }
  }

  return (
    <Collapsible open={isEditorOpen} onOpenChange={handleEditorOpenChange}>
      <Card className="mt-6" data-testid="portfolio-chart-section">
        <CardHeader className="gap-3 sm:flex sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="text-base">Amount invested</CardTitle>
            <div className="mt-1 text-sm text-muted-foreground">
              {account ? account : 'Select an account'}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!account}
              >
                <Pencil className="size-4" />
                Edit amount invested
              </Button>
            </CollapsibleTrigger>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {error ? (
            <PortfolioChartEmptyState message={error} />
          ) : isLoading ? (
            <PortfolioChartEmptyState message="Loading saved values..." />
          ) : hasSavedValues ? (
            <MetricBarChart currency={currency} data={monthlyRows}
              metric="amount_invested" />
          ) : (
            <PortfolioChartEmptyState message="No monthly amount invested saved yet." />
          )}

          <CollapsibleContent>
            <div data-testid="portfolio-chart-values-editor">
              {saveError ? (
                <div className="mt-4 text-sm text-destructive">{saveError}</div>
              ) : null}
              <PortfolioChartValuesEditor
                account={account}
                draftRows={draftRows}
                isSaving={isSaving}
                onAddRow={handleAddDraftRow}
                onCancel={handleCancel}
                onChangeRow={handleChangeDraftRow}
                onDeleteRow={handleDeleteDraftRow}
                onSave={() => void handleSave()}
              />
            </div>
          </CollapsibleContent>
        </CardContent>
      </Card>
    </Collapsible>
  )
}

function MetricBarChart({
  currency,
  data,
  metric,
}: {
  currency: string
  data: PortfolioMonthlyChartRow[]
  metric: PortfolioChartMetricKey
}) {
  return (
    <section className="min-w-0" aria-label="Amount invested chart">
      <ChartContainer
        config={chartConfig}
        className="h-72 w-full"
        initialDimension={{ width: 520, height: 288 }}
      >
        <BarChart accessibilityLayer data={data} margin={{ left: 8, right: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
          />
          <YAxis
            tickFormatter={(value) => formatCompactCurrency(value, currency)}
            tickLine={false}
            axisLine={false}
            width={72}
          />
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value) =>
                  formatOptionalCurrency(Number(value), currency)
                }
              />
            }
          />
          <Bar
            dataKey={metric}
            fill={`var(--color-${metric})`}
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ChartContainer>
    </section>
  )
}

function PortfolioChartEmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed bg-muted/20 px-4 text-center text-sm text-muted-foreground">
      {message}
    </div>
  )
}

function savedRowsToDraftRows(rows: PortfolioChartValue[]) {
  return normalizePortfolioChartValues(rows).map((row) => ({
    month: row.month,
    amount_invested: row.amount_invested?.toString() ?? '',
  }))
}

function editorPreviewRows(
  isEditorOpen: boolean,
  draftRows: PortfolioChartValueDraftRow[],
  savedRows: PortfolioChartValue[],
): PortfolioChartValueInput[] {
  if (!isEditorOpen) {
    return savedRows
  }

  try {
    return parsePortfolioChartValueDraftRows(draftRows)
  } catch {
    return savedRows
  }
}
