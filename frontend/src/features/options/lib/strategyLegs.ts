import type { OptionRight } from '@/api/orders'

export type DraftOptionLeg = {
  ticker: string
  expiration: string
  right: OptionRight
  strike: number
  signedQuantity: number
  quote: number | null
  bid: number | null
  ask: number | null
}

export type OptionQuoteSelection = {
  ticker: string
  expiration: string
  right: OptionRight
  strike: number
  action: 'BUY' | 'SELL'
  quote: number | null
  bid: number | null
  ask: number | null
}

export function mergeOptionQuoteSelection(
  legs: DraftOptionLeg[],
  selection: OptionQuoteSelection,
) {
  const signedDelta = selection.action === 'BUY' ? 1 : -1
  const existingIndex = legs.findIndex((leg) => sameOptionLeg(leg, selection))

  if (existingIndex < 0) {
    return [
      ...legs,
      {
        ticker: selection.ticker,
        expiration: selection.expiration,
        right: selection.right,
        strike: selection.strike,
        signedQuantity: signedDelta,
        quote: selection.quote,
        bid: selection.bid,
        ask: selection.ask,
      },
    ]
  }

  return legs
    .map((leg, index) =>
      index === existingIndex
        ? {
            ...leg,
            signedQuantity: leg.signedQuantity + signedDelta,
            quote: selection.quote,
            bid: selection.bid,
            ask: selection.ask,
          }
        : leg,
    )
    .filter((leg) => leg.signedQuantity !== 0)
}

function sameOptionLeg(
  first: Pick<DraftOptionLeg, 'ticker' | 'expiration' | 'right' | 'strike'>,
  second: Pick<DraftOptionLeg, 'ticker' | 'expiration' | 'right' | 'strike'>,
) {
  return (
    first.ticker === second.ticker &&
    first.expiration === second.expiration &&
    first.right === second.right &&
    first.strike === second.strike
  )
}
