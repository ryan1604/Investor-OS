import { Fragment } from 'react'

import type { EditingCell } from '@/features/stock-analysis/lib/editingCell'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatDisplayValue,
  formatDraftValue,
  formatEditableValue,
  formatMultiplierValue,
} from '@/features/stock-analysis/lib/valuationFormatting'
import {
  YEAR_INDEXES,
  getValuationCellKind,
  type CalculatedScenario,
  type ScenarioKey,
  type YearIndex,
} from '@/features/stock-analysis/lib/valuationModel'
import {
  VALUATION_TABLE_ROW_DEFINITIONS,
  isSharePriceRow,
  hasSpacerAfter,
  valuationRowMetadata,
  type EditableRowKey,
  type ValuationRowKey,
} from '@/features/stock-analysis/lib/valuationRows'

const SCENARIO_LABELS: Record<ScenarioKey, string> = {
  bull: 'Bull case',
  base: 'Base case',
  bear: 'Bear case',
}

export function ScenarioValuationTable({
  calculatedScenario,
  scenario,
  yearHeaders,
  editingCell,
  onCellCommit,
  onEditingCellChange,
}: {
  calculatedScenario: CalculatedScenario
  scenario: ScenarioKey
  yearHeaders: string[]
  editingCell: EditingCell | null
  onCellCommit: (
    scenario: ScenarioKey,
    row: EditableRowKey,
    yearIndex: YearIndex,
    value: string,
  ) => void
  onEditingCellChange: (editingCell: EditingCell | null) => void
}) {
  return (
    <section className="min-w-0 space-y-3">
      <h3 className="text-base font-medium">{SCENARIO_LABELS[scenario]}</h3>
      <div className="border-t">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-64">Metric</TableHead>
              {yearHeaders.map((yearHeader) => (
                <TableHead className="text-right" key={yearHeader}>
                  {yearHeader}
                </TableHead>
              ))}
              <TableHead className="text-right">Multiplier</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {VALUATION_TABLE_ROW_DEFINITIONS.map((row) => (
              <Fragment key={row.key}>
                <TableRow>
                  <TableCell className="font-medium text-muted-foreground">
                    {row.label}
                  </TableCell>
                  {YEAR_INDEXES.map((yearIndex) => (
                    <ValuationCell
                      calculatedScenario={calculatedScenario}
                      key={yearIndex}
                      row={row.key}
                      scenario={scenario}
                      yearHeader={yearHeaders[yearIndex]}
                      yearIndex={yearIndex}
                      editingCell={editingCell}
                      onCellCommit={onCellCommit}
                      onEditingCellChange={onEditingCellChange}
                    />
                  ))}
                  <MultiplierCell calculatedScenario={calculatedScenario} row={row.key} />
                </TableRow>
                {hasSpacerAfter(row.key) ? (
                  <TableRow
                    aria-hidden="true"
                    className="h-8 border-0 hover:bg-transparent"
                  >
                    <TableCell
                      className="p-0"
                      colSpan={YEAR_INDEXES.length + 2}
                    />
                  </TableRow>
                ) : null}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}

function MultiplierCell({
  calculatedScenario,
  row,
}: {
  calculatedScenario: CalculatedScenario
  row: ValuationRowKey
}) {
  if (!isSharePriceRow(row)) {
    return <TableCell className="min-w-28" />
  }

  return (
    <TableCell className="min-w-28 bg-muted/20 text-right tabular-nums text-muted-foreground">
      {formatMultiplierValue(calculatedScenario.multipliers[row])}
    </TableCell>
  )
}

function ValuationCell({
  calculatedScenario,
  row,
  scenario,
  yearHeader,
  yearIndex,
  editingCell,
  onCellCommit,
  onEditingCellChange,
}: {
  calculatedScenario: CalculatedScenario
  row: ValuationRowKey
  scenario: ScenarioKey
  yearHeader: string
  yearIndex: YearIndex
  editingCell: EditingCell | null
  onCellCommit: (
    scenario: ScenarioKey,
    row: EditableRowKey,
    yearIndex: YearIndex,
    value: string,
  ) => void
  onEditingCellChange: (editingCell: EditingCell | null) => void
}) {
  const cellKind = getValuationCellKind(row, yearIndex)

  if (cellKind === 'editable') {
    const editableRow = row as EditableRowKey
    const value = calculatedScenario.editable[editableRow][yearIndex]
    const cellId = getCellId(scenario, editableRow, yearIndex)
    const isEditing = editingCell?.id === cellId
    const displayValue = isEditing
      ? editingCell.draftValue
      : formatEditableValue(row, value)

    return (
      <TableCell>
        <Input
          aria-label={`${SCENARIO_LABELS[scenario]} ${rowLabel(row)} ${yearHeader}`}
          className="min-w-28 border-destructive/35 bg-destructive/5 text-right focus-visible:border-destructive/70 focus-visible:ring-destructive/20"
          inputMode="decimal"
          value={displayValue}
          onBlur={() => {
            if (isEditing) {
              onCellCommit(scenario, editableRow, yearIndex, editingCell.draftValue)
            }
          }}
          onChange={(event) =>
            onEditingCellChange({ id: cellId, draftValue: event.target.value })
          }
          onFocus={() =>
            onEditingCellChange({
              id: cellId,
              draftValue: formatDraftValue(value),
            })
          }
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault()
              onEditingCellChange(null)
              event.currentTarget.blur()
            }

            if (event.key === 'Enter') {
              event.preventDefault()
              onCellCommit(
                scenario,
                editableRow,
                yearIndex,
                isEditing ? editingCell.draftValue : displayValue,
              )
              event.currentTarget.blur()
            }
          }}
        />
      </TableCell>
    )
  }

  const value =
    row in calculatedScenario.derived
      ? calculatedScenario.derived[
          row as keyof typeof calculatedScenario.derived
        ][yearIndex]
      : null

  return (
    <TableCell className="min-w-28 bg-muted/20 text-right tabular-nums text-muted-foreground">
      {formatDisplayValue(row, value)}
    </TableCell>
  )
}

function getCellId(
  scenario: ScenarioKey,
  row: EditableRowKey,
  yearIndex: YearIndex,
) {
  return `${scenario}:${row}:${yearIndex}`
}

function rowLabel(row: ValuationRowKey) {
  return valuationRowMetadata(row)?.label ?? row
}
