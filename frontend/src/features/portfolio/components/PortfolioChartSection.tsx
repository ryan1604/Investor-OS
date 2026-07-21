import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { Pencil } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type {
  PortfolioChartValue,
  PortfolioChartValueRequest,
} from '@/api/portfolioChartValues'
import { errorMessage } from '@/api/client'
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
  ToggleGroup,
  ToggleGroupItem,
} from '@/components/ui/toggle-group'
import {
  PortfolioChartValuesEditor,
} from '@/features/portfolio/components/PortfolioChartValuesEditor'
import {
  formatCompactCurrency,
  formatTooltipCurrency,
  normalizePortfolioChartValues,
  parsePortfolioChartValueDraftRows,
  toSimpleYearChartRows,
  type PortfolioChartValueDraftRow,
  type PortfolioChartValueInput,
  type PortfolioChartMetricKey,
  type PortfolioMonthlyChartRow,
  type PortfolioSimpleYearChartRow,
} from '@/features/portfolio/lib/chartValues'

type PortfolioChartViewMode = 'advanced' | 'simple'

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
  portfolio_value: {
    label: 'Portfolio value',
    color: 'var(--chart-portfolio-value)',
  },
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
  const [viewMode, setViewMode] = useState<PortfolioChartViewMode>('advanced')
  const [isEditorOpen, setIsEditorOpen] = useState(false)
  const [draftRows, setDraftRows] = useState<PortfolioChartValueDraftRow[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const accountRef = useRef(account)
  const previewRows = useMemo(
    () => editorPreviewRows(isEditorOpen, draftRows, rows),
    [isEditorOpen, draftRows, rows],
  )
  const monthlyRows = useMemo(
    () => normalizePortfolioChartValues(previewRows),
    [previewRows],
  )
  const yearlyRows = useMemo(
    () => toSimpleYearChartRows(previewRows),
    [previewRows],
  )
  const hasSavedValues = monthlyRows.length > 0

  useEffect(() => {
    accountRef.current = account
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
      { month: '', portfolio_value: '', amount_invested: '' },
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
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="text-base">Portfolio history</CardTitle>
            <div className="mt-1 text-sm text-muted-foreground">
              {account ? account : 'Select an account'}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              value={viewMode}
              onValueChange={(value) => {
                if (value === 'advanced' || value === 'simple') {
                  setViewMode(value)
                }
              }}
              variant="outline"
              size="sm"
              aria-label="Portfolio chart view"
            >
              <ToggleGroupItem value="advanced">Advanced</ToggleGroupItem>
              <ToggleGroupItem value="simple">Simple</ToggleGroupItem>
            </ToggleGroup>
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!account}
              >
                <Pencil className="size-4" />
                Edit values
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
            viewMode === 'advanced' ? (
              <div className="grid gap-4 xl:grid-cols-2">
                <MetricBarChart
                  currency={currency}
                  data={monthlyRows}
                  metric="portfolio_value"
                  title="Portfolio value"
                />
                <MetricBarChart
                  currency={currency}
                  data={monthlyRows}
                  metric="amount_invested"
                  title="Amount invested"
                />
              </div>
            ) : yearlyRows.length ? (
              <GroupedYearlyBarChart currency={currency} data={yearlyRows} />
            ) : (
              <PortfolioChartEmptyState message="No December values saved yet." />
            )
          ) : (
            <PortfolioChartEmptyState message="No saved portfolio history yet." />
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
  title,
}: {
  currency: string
  data: PortfolioMonthlyChartRow[]
  metric: PortfolioChartMetricKey
  title: string
}) {
  return (
    <section className="min-w-0 rounded-lg border bg-card/50 p-3">
      <h3 className="text-sm font-medium">{title}</h3>
      <ChartContainer
        config={chartConfig}
        className="mt-3 h-72 w-full"
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
                  formatTooltipCurrency(Number(value), currency)
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

function GroupedYearlyBarChart({
  currency,
  data,
}: {
  currency: string
  data: PortfolioSimpleYearChartRow[]
}) {
  return (
    <section className="min-w-0 rounded-lg border bg-card/50 p-3">
      <h3 className="text-sm font-medium">End-of-year values</h3>
      <ChartContainer
        config={chartConfig}
        className="mt-3 h-80 w-full"
        initialDimension={{ width: 760, height: 320 }}
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
                  formatTooltipCurrency(Number(value), currency)
                }
              />
            }
          />
          <Bar
            dataKey="portfolio_value"
            fill="var(--color-portfolio_value)"
            radius={[4, 4, 0, 0]}
          />
          <Bar
            dataKey="amount_invested"
            fill="var(--color-amount_invested)"
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
    portfolio_value: row.portfolio_value?.toString() ?? '',
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
