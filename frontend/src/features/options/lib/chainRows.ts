import type { OptionChainResponse, OptionChainRow } from '@/api/options'

export function mergeLiveChainSnapshot(
  chain: OptionChainResponse | null,
  ticker: string,
  expiration: string,
  rows: OptionChainRow[],
  message: string | null,
): OptionChainResponse {
  if (!chain || chain.expiration !== expiration || !chain.rows.length) {
    return {
      ticker,
      expiration,
      underlying_price: chain?.underlying_price ?? null,
      rows,
      message: message ?? chain?.message ?? null,
    }
  }

  return rows.reduce(
    (nextChain, row) =>
      mergeLiveChainRow(nextChain, ticker, expiration, row, message),
    chain,
  )
}

export function mergeLiveChainRow(
  chain: OptionChainResponse | null,
  ticker: string,
  expiration: string,
  row: OptionChainRow,
  message: string | null,
): OptionChainResponse {
  const currentRows = chain?.rows ?? []
  const rowIndex = currentRows.findIndex(
    (currentRow) => currentRow.strike === row.strike,
  )
  const rows =
    rowIndex >= 0
      ? currentRows.map((currentRow, index) =>
          index === rowIndex
            ? {
                ...currentRow,
                call: row.call ?? currentRow.call,
                put: row.put ?? currentRow.put,
              }
            : currentRow,
        )
      : [...currentRows, row].sort((first, second) => first.strike - second.strike)

  return {
    ticker,
    expiration,
    underlying_price: chain?.underlying_price ?? null,
    rows,
    message: message ?? chain?.message ?? null,
  }
}
