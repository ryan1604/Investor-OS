import type { PortfolioPosition } from '@/api/portfolio'
import { formatNumber } from '@/lib/format'

export type SortKey =
  | 'instrument'
  | 'last_price'
  | 'change_percent'
  | 'pnl'
  | 'pnl_percent'
  | 'unrealized_pnl'
  | 'unrealized_pnl_percent'
  | 'market_value'
  | 'quantity'
  | 'cost_basis'
  | 'average_price'
  | 'net_liquidity_percent'

export type SortDirection = 'asc' | 'desc'

export type SortState = {
  key: SortKey
  direction: SortDirection
}

export type DisplayPosition = PortfolioPosition & {
  instrumentTitle: string
  instrumentDetail: string | null
}

export const DEFAULT_SORT: SortState = {
  key: 'net_liquidity_percent',
  direction: 'desc',
}

function positionIdentityKey(position: DisplayPosition) {
  return [
    position.account,
    position.symbol,
    position.sec_type,
    position.local_symbol,
    position.expiry,
    position.strike,
    position.right,
    position.multiplier,
    position.exchange,
    position.currency,
    position.instrumentTitle,
    position.instrumentDetail,
  ].join('-')
}

export function positionKeys(positions: DisplayPosition[]) {
  const identityCounts = new Map<string, number>()

  return positions.map((position) => {
    const identityKey = positionIdentityKey(position)
    const count = identityCounts.get(identityKey) ?? 0

    identityCounts.set(identityKey, count + 1)

    return count === 0 ? identityKey : `${identityKey}-${count}`
  })
}

function cleanDisplayPrice(value: number | null) {
  if (value === null || value <= 0) {
    return null
  }

  return value
}

function parsedExpiry(value: string | null) {
  if (!value) {
    return null
  }

  if (value.length === 8) {
    const year = Number(value.slice(0, 4))
    const month = Number(value.slice(4, 6))
    const day = Number(value.slice(6))

    if (year && month && day) {
      return new Date(Date.UTC(year, month - 1, day))
    }
  }

  return null
}

function formatExpiry(value: string | null, includeYear = true) {
  const expiry = parsedExpiry(value)

  if (!expiry) {
    return value
  }

  const formattedDate = expiry.toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    timeZone: 'UTC',
  })

  if (!includeYear) {
    return formattedDate
  }

  return `${formattedDate} '${String(expiry.getUTCFullYear()).slice(-2)}`
}

function formatOptionRight(value: string | null) {
  if (value === 'C') {
    return 'Call'
  }

  if (value === 'P') {
    return 'Put'
  }

  return value
}

function formatStrike(value: number | null) {
  if (value === null || !Number.isFinite(value)) {
    return null
  }

  return formatNumber(value, { maximumFractionDigits: 4 })
}

function optionDetail(position: PortfolioPosition, includeYear = true) {
  const expiry = formatExpiry(position.expiry, includeYear)
  const strike = formatStrike(position.strike)
  const right = formatOptionRight(position.right)

  return [expiry, strike, right].filter(Boolean).join(' ')
}

function strategyName(legs: PortfolioPosition[]) {
  if (legs.length !== 2) {
    return null
  }

  const [first, second] = [...legs].sort(
    (left, right) => (left.strike ?? 0) - (right.strike ?? 0),
  )

  if (
    first.right === 'P' &&
    second.right === 'P' &&
    first.quantity > 0 &&
    second.quantity < 0
  ) {
    return 'Bull Put'
  }

  if (
    first.right === 'C' &&
    second.right === 'C' &&
    first.quantity < 0 &&
    second.quantity > 0
  ) {
    return 'Bear Call'
  }

  if (
    first.right === 'P' &&
    second.right === 'P' &&
    first.quantity < 0 &&
    second.quantity > 0
  ) {
    return 'Bear Put'
  }

  if (
    first.right === 'C' &&
    second.right === 'C' &&
    first.quantity > 0 &&
    second.quantity < 0
  ) {
    return 'Bull Call'
  }

  return null
}

function sumValues(
  positions: PortfolioPosition[],
  key: keyof PortfolioPosition,
) {
  const values = positions
    .map((position) => position[key])
    .filter((value): value is number => typeof value === 'number')

  if (!values.length) {
    return null
  }

  return values.reduce((sum, value) => sum + value, 0)
}

function percentOf(numerator: number | null, denominator: number | null) {
  if (numerator === null || denominator === null || denominator === 0) {
    return null
  }

  return (numerator / Math.abs(denominator)) * 100
}

function spreadQuantity(legs: PortfolioPosition[]) {
  const quantities = legs.map((leg) => Math.abs(leg.quantity))

  if (!quantities.length) {
    return 0
  }

  return Math.min(...quantities)
}

function toDisplayPosition(position: PortfolioPosition): DisplayPosition {
  const lastPrice = cleanDisplayPrice(position.last_price)

  if (position.sec_type !== 'OPT') {
    return {
      ...position,
      last_price: lastPrice,
      instrumentTitle: position.symbol,
      instrumentDetail: null,
    }
  }

  return {
    ...position,
    last_price: lastPrice,
    instrumentTitle: position.symbol,
    instrumentDetail: optionDetail(position),
  }
}

function spreadDisplayPosition(
  legs: PortfolioPosition[],
): DisplayPosition | null {
  const name = strategyName(legs)

  if (!name) {
    return null
  }

  const sortedLegs = [...legs].sort(
    (first, second) => (second.strike ?? 0) - (first.strike ?? 0),
  )
  const baseLeg = sortedLegs[0]
  const pnl = sumValues(legs, 'pnl')
  const unrealizedPnl = sumValues(legs, 'unrealized_pnl')
  const costBasis = sumValues(legs, 'cost_basis')
  const strikes = sortedLegs.map((leg) => formatStrike(leg.strike)).filter(Boolean)
  const detail = [formatExpiry(baseLeg.expiry, false), strikes.join('/'), name]
    .filter(Boolean)
    .join(' ')

  return {
    ...baseLeg,
    quantity: spreadQuantity(legs),
    last_price: null,
    change_percent: null,
    pnl,
    pnl_percent: percentOf(pnl, baseLeg.net_liquidity),
    unrealized_pnl: unrealizedPnl,
    unrealized_pnl_percent: percentOf(unrealizedPnl, costBasis),
    market_value: sumValues(legs, 'market_value'),
    cost_basis: costBasis,
    average_price: null,
    net_liquidity_percent: sumValues(legs, 'net_liquidity_percent'),
    instrumentTitle: `${baseLeg.symbol} ${name.replace(' Put', ' Spread').replace(
      ' Call',
      ' Spread',
    )}`,
    instrumentDetail: detail,
  }
}

export function groupDisplayPositions(positions: PortfolioPosition[]) {
  const displayPositions: DisplayPosition[] = []
  const optionGroups = new Map<string, PortfolioPosition[]>()

  for (const position of positions) {
    if (
      position.sec_type !== 'OPT' ||
      position.expiry === null ||
      position.right === null
    ) {
      displayPositions.push(toDisplayPosition(position))
      continue
    }

    const key = [
      position.account,
      position.symbol,
      position.expiry,
      position.right,
      position.currency,
    ].join('|')

    optionGroups.set(key, [...(optionGroups.get(key) ?? []), position])
  }

  for (const legs of optionGroups.values()) {
    const spread = spreadDisplayPosition(legs)

    if (spread) {
      displayPositions.push(spread)
      continue
    }

    displayPositions.push(...legs.map(toDisplayPosition))
  }

  return displayPositions
}

function sortValue(position: DisplayPosition, key: SortKey) {
  if (key === 'instrument') {
    return `${position.instrumentTitle} ${position.instrumentDetail ?? ''}`
  }

  return position[key]
}

export function comparePositions(
  first: DisplayPosition,
  second: DisplayPosition,
  sort: SortState,
) {
  const firstValue = sortValue(first, sort.key)
  const secondValue = sortValue(second, sort.key)

  if (firstValue === null && secondValue === null) {
    return 0
  }

  if (firstValue === null) {
    return 1
  }

  if (secondValue === null) {
    return -1
  }

  const direction = sort.direction === 'asc' ? 1 : -1

  if (typeof firstValue === 'string' && typeof secondValue === 'string') {
    return firstValue.localeCompare(secondValue) * direction
  }

  return (Number(firstValue) - Number(secondValue)) * direction
}

export function nextSortDirection(key: SortKey, currentSort: SortState) {
  if (key === currentSort.key) {
    return currentSort.direction === 'asc' ? 'desc' : 'asc'
  }

  return key === 'instrument' ? 'asc' : 'desc'
}
