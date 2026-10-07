import type { OptionChainResponse, OptionChainRow } from '@/api/options'

export function mergeLiveChainRows(
  chain: OptionChainResponse | null,
  ticker: string,
  expiration: string,
  rows: OptionChainRow[],
  message: string | null,
): OptionChainResponse {
  if (!rows.length) {
    return {
      ticker,
      expiration,
      underlying_price: chain?.underlying_price ?? null,
      rows: chain?.rows ?? [],
      message: message ?? chain?.message ?? null,
      warning: chain?.warning ?? null,
    }
  }

  const currentRows = chain?.rows ?? []
  const nextRows = [...currentRows]
  const rowIndexes = createStrikeIndex(nextRows)
  let didAppendRow = false

  for (const row of rows) {
    const rowIndex = rowIndexes.get(row.strike)

    if (rowIndex === undefined) {
      rowIndexes.set(row.strike, nextRows.length)
      nextRows.push(row)
      didAppendRow = true
      continue
    }

    const currentRow = nextRows[rowIndex]
    nextRows[rowIndex] = {
      ...currentRow,
      call: row.call ?? currentRow.call,
      put: row.put ?? currentRow.put,
    }
  }

  if (didAppendRow) {
    nextRows.sort((first, second) => first.strike - second.strike)
  }

  return {
    ticker,
    expiration,
    underlying_price: chain?.underlying_price ?? null,
    rows: nextRows,
    message: message ?? chain?.message ?? null,
    warning: chain?.warning ?? null,
  }
}

export function mergeLiveChainSnapshot(
  chain: OptionChainResponse | null,
  ticker: string,
  expiration: string,
  rows: OptionChainRow[],
  message: string | null,
  warning: string | null = null,
): OptionChainResponse {
  return {
    ticker,
    expiration,
    underlying_price: chain?.underlying_price ?? null,
    rows,
    message: message ?? chain?.message ?? null,
    warning,
  }
}

export function mergeLiveChainRow(
  chain: OptionChainResponse | null,
  ticker: string,
  expiration: string,
  row: OptionChainRow,
  message: string | null,
): OptionChainResponse {
  return mergeLiveChainRows(chain, ticker, expiration, [row], message)
}

function createStrikeIndex(rows: OptionChainRow[]) {
  return new Map(rows.map((row, index) => [row.strike, index]))
}
