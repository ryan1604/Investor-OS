
export type PortfolioChartMetricKey = 'amount_invested'

export type PortfolioChartValueInput = {
  month: string
  amount_invested: number | null
}

export type PortfolioMonthlyChartRow = PortfolioChartValueInput & {
  label: string
}

export type PortfolioChartValueDraftRow = {
  month: string
  amount_invested?: string | number | null
}

type PortfolioChartValueValidationField =
  | 'month'
  | 'amount_invested'
  | 'row'

type PortfolioChartValueValidationIssue = {
  index: number
  field: PortfolioChartValueValidationField
  message: string
}

type ParsedPortfolioChartValueDraftRow = {
  month: string
  amount_invested: number | null
}

const MONTH_KEY_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/

const shortMonthFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  timeZone: 'UTC',
  year: '2-digit',
})

export function normalizePortfolioChartValues(
  rows: PortfolioChartValueInput[],
): PortfolioMonthlyChartRow[] {
  return rows
    .map((row) => ({
      month: row.month,
      amount_invested: row.amount_invested,
      label: formatMonthLabel(row.month),
    }))
    .sort(compareChartMonths)
}

export function validatePortfolioChartValueRows(
  rows: PortfolioChartValueDraftRow[],
) {
  const issues: PortfolioChartValueValidationIssue[] = []
  const monthsByValue = new Map<string, number[]>()

  rows.forEach((row, index) => {
    const month = row.month.trim()

    if (!month) {
      issues.push({
        index,
        field: 'month',
        message: 'Month is required.',
      })
    } else if (!isValidChartMonth(month)) {
      issues.push({
        index,
        field: 'month',
        message: 'Month must use YYYY-MM format.',
      })
    } else {
      monthsByValue.set(month, [...(monthsByValue.get(month) ?? []), index])
    }

    const amountInvested = parseDraftNumber(row.amount_invested)

    if (amountInvested === 'invalid') {
      issues.push({
        index,
        field: 'amount_invested',
        message: 'Amount invested must be a valid number.',
      })
    }

    if (amountInvested === null) {
      issues.push({
        index,
        field: 'row',
        message: 'Amount invested is required.',
      })
    }
  })

  for (const duplicateIndexes of monthsByValue.values()) {
    if (duplicateIndexes.length > 1) {
      duplicateIndexes.forEach((index) => {
        issues.push({
          index,
          field: 'month',
          message: 'Month must be unique.',
        })
      })
    }
  }

  return issues
}

export function parsePortfolioChartValueDraftRows(
  rows: PortfolioChartValueDraftRow[],
): ParsedPortfolioChartValueDraftRow[] {
  const issues = validatePortfolioChartValueRows(rows)

  if (issues.length > 0) {
    throw new Error('Portfolio chart value rows are invalid.')
  }

  return rows
    .map((row) => ({
      month: row.month.trim(),
      amount_invested: validDraftNumber(row.amount_invested),
    }))
    .sort(compareChartMonths)
}

function isValidChartMonth(month: string) {
  return MONTH_KEY_PATTERN.test(month.trim())
}

export function formatMonthLabel(month: string) {
  return shortMonthFormatter.format(monthDate(month))
}

function compareChartMonths(
  first: PortfolioChartValueInput,
  second: PortfolioChartValueInput,
) {
  return first.month.localeCompare(second.month)
}

function parseDraftNumber(value: string | number | null | undefined) {
  if (value === null || value === undefined) {
    return null
  }

  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 'invalid'
  }

  const normalizedValue = value.trim()

  if (!normalizedValue) {
    return null
  }

  const numericValue = Number(normalizedValue)
  return Number.isFinite(numericValue) ? numericValue : 'invalid'
}

function validDraftNumber(value: string | number | null | undefined) {
  const parsedValue = parseDraftNumber(value)

  if (parsedValue === 'invalid') {
    throw new Error('Portfolio chart value rows are invalid.')
  }

  return parsedValue
}

function monthDate(month: string) {
  const [year, monthNumber] = month.split('-').map(Number)
  return new Date(Date.UTC(year, monthNumber - 1, 1))
}
