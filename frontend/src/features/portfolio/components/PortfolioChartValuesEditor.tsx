import { Plus, Trash2 } from 'lucide-react'
import { useMemo } from 'react'

import { Button } from '@/components/ui/button'
import {
  Field,
  FieldError,
  FieldGroup,
} from '@/components/ui/field'
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
  validatePortfolioChartValueRows,
  type PortfolioChartValueDraftRow,
} from '@/features/portfolio/lib/chartValues'

type PortfolioChartValuesEditorProps = {
  account: string | undefined
  draftRows: PortfolioChartValueDraftRow[]
  isSaving: boolean
  onAddRow: () => void
  onCancel: () => void
  onChangeRow: (
    index: number,
    field: keyof PortfolioChartValueDraftRow,
    value: string,
  ) => void
  onDeleteRow: (index: number) => void
  onSave: () => void
}

export function PortfolioChartValuesEditor({
  account,
  draftRows,
  isSaving,
  onAddRow,
  onCancel,
  onChangeRow,
  onDeleteRow,
  onSave,
}: PortfolioChartValuesEditorProps) {
  const validationIssues = useMemo(
    () => validatePortfolioChartValueRows(draftRows),
    [draftRows],
  )
  const canSave = Boolean(account) && validationIssues.length === 0 && !isSaving

  return (
    <div className="mt-4 rounded-lg border bg-muted/15 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">Monthly amount invested</div>
        <Button type="button" size="sm" variant="outline" onClick={onAddRow}>
          <Plus className="size-4" />
          Add month
        </Button>
      </div>

      <FieldGroup>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-36">Month</TableHead>
              <TableHead className="min-w-44">Amount invested</TableHead>
              <TableHead className="w-16 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {draftRows.map((row, index) => (
              <TableRow key={index}>
                <TableCell>
                  <Input
                    aria-label={`Month ${index + 1}`}
                    placeholder="YYYY-MM"
                    value={row.month}
                    onChange={(event) =>
                      onChangeRow(index, 'month', event.target.value)
                    }
                  />
                </TableCell>
                <TableCell>
                  <Input
                    aria-label={`Amount invested ${index + 1}`}
                    inputMode="decimal"
                    placeholder="100000"
                    value={row.amount_invested ?? ''}
                    onChange={(event) =>
                      onChangeRow(index, 'amount_invested', event.target.value)
                    }
                  />
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete row ${index + 1}`}
                    onClick={() => onDeleteRow(index)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {validationIssues.length > 0 ? (
          <Field>
            {validationIssues.map((issue) => (
              <FieldError key={`${issue.index}-${issue.field}-${issue.message}`}>
                Row {issue.index + 1}: {issue.message}
              </FieldError>
            ))}
          </Field>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isSaving}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={!canSave} onClick={onSave}>
            {isSaving ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </FieldGroup>
    </div>
  )
}
