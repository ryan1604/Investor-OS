type OptionSide = 'call' | 'put'

export function optionReturnPercent(
  side: OptionSide,
  mid: number | null,
  strike: number | null,
  underlyingPrice: number | null,
) {
  if (mid === null) {
    return null
  }

  if (side === 'put') {
    return strike === null || strike <= 0 ? null : (mid * 100) / strike
  }

  return underlyingPrice === null || underlyingPrice <= 0
    ? null
    : (mid * 100) / underlyingPrice
}
