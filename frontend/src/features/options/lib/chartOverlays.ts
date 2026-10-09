import type { OrderRecord, OptionRight } from '@/api/orders'
import type { PortfolioPosition, PortfolioResponse } from '@/api/portfolio'
import type { DraftOptionLeg } from '@/features/options/lib/strategyLegs'

export type ChartOptionOverlaySource = 'draft' | 'working' | 'held'

type ChartOptionStrikeOverlay = {
  type: 'option-strike'
  key: string
  ticker: string
  expiration: string
  right: OptionRight
  strike: number
  signedQuantity: number
  sources: ChartOptionOverlaySource[]
  label: string
}

type ChartCostBasisOverlay = {
  type: 'stock-cost-basis'
  key: string
  price: number
  label: string
}

export type ChartOverlay = ChartCostBasisOverlay | ChartOptionStrikeOverlay

export function chartOverlays({
  draftLegs,
  orders,
  portfolio,
  selectedAccount,
  ticker,
}: {
  draftLegs: DraftOptionLeg[]
  orders: OrderRecord[]
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  ticker: string
}): ChartOverlay[] {
  const normalizedTicker = ticker.toUpperCase()
  return [
    ...stockCostBasisOverlays(portfolio, selectedAccount, normalizedTicker),
    ...optionStrikeOverlays({
      draftLegs,
      orders,
      portfolio,
      selectedAccount,
      ticker: normalizedTicker,
    }),
  ]
}

function stockCostBasisOverlays(
  portfolio: PortfolioResponse | null,
  selectedAccount: string | null,
  ticker: string,
) {
  if (!portfolio || !selectedAccount) {
    return []
  }

  return portfolio.positions
    .filter(
      (position) =>
        position.account === selectedAccount &&
        position.symbol.toUpperCase() === ticker &&
        position.sec_type === 'STK' &&
        position.quantity !== 0 &&
        stockCostBasisPrice(position) !== null,
    )
    .map<ChartCostBasisOverlay>((position) => ({
      type: 'stock-cost-basis',
      key: `stock-cost-basis:${position.account}:${position.symbol}`,
      price: stockCostBasisPrice(position) ?? 0,
      label: 'Cost basis',
    }))
}

function optionStrikeOverlays({
  draftLegs,
  orders,
  portfolio,
  selectedAccount,
  ticker,
}: {
  draftLegs: DraftOptionLeg[]
  orders: OrderRecord[]
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  ticker: string
}) {
  const overlays = new Map<string, ChartOptionStrikeOverlay>()

  if (selectedAccount) {
    for (const leg of draftLegs) {
      if (leg.ticker.toUpperCase() !== ticker) {
        continue
      }
      addOptionOverlay(overlays, {
        ticker,
        expiration: leg.expiration,
        right: leg.right,
        strike: leg.strike,
        signedQuantity: leg.signedQuantity,
        source: 'draft',
      })
    }
  }

  for (const order of orders) {
    if (
      !selectedAccount ||
      !order.is_open ||
      order.parent_order_id !== null ||
      order.preview.request.order_kind !== 'option_strategy' ||
      order.account !== selectedAccount
    ) {
      continue
    }

    for (const leg of order.preview.request.legs) {
      if (leg.ticker.toUpperCase() !== ticker) {
        continue
      }
      addOptionOverlay(overlays, {
        ticker,
        expiration: normalizeExpiration(leg.expiration),
        right: leg.right,
        strike: leg.strike,
        signedQuantity: leg.action === 'BUY' ? leg.quantity : -leg.quantity,
        source: 'working',
      })
    }
  }

  for (const position of portfolio?.positions ?? []) {
    const heldLeg = optionPositionToLeg(position, selectedAccount, ticker)
    if (!heldLeg) {
      continue
    }
    addOptionOverlay(overlays, { ...heldLeg, source: 'held' })
  }

  return Array.from(overlays.values()).filter(
    (overlay) => overlay.signedQuantity !== 0,
  )
}

function optionPositionToLeg(
  position: PortfolioPosition,
  selectedAccount: string | null,
  ticker: string,
) {
  if (
    !selectedAccount ||
    position.sec_type !== 'OPT' ||
    position.symbol.toUpperCase() !== ticker ||
    position.expiry === null ||
    position.right === null ||
    position.strike === null ||
    position.quantity === 0 ||
    position.account !== selectedAccount
  ) {
    return null
  }

  const right: OptionRight | null =
    position.right === 'C' ? 'CALL' : position.right === 'P' ? 'PUT' : null
  if (right === null) {
    return null
  }

  return {
    ticker,
    expiration: position.expiry,
    right,
    strike: position.strike,
    signedQuantity: position.quantity,
  }
}

function addOptionOverlay(
  overlays: Map<string, ChartOptionStrikeOverlay>,
  leg: {
    ticker: string
    expiration: string
    right: OptionRight
    strike: number
    signedQuantity: number
    source: ChartOptionOverlaySource
  },
) {
  const key = optionOverlayKey(leg)
  const expiration = normalizeExpiration(leg.expiration)
  const current = overlays.get(key)
  const signedQuantity = (current?.signedQuantity ?? 0) + leg.signedQuantity
  const sources = current?.sources.includes(leg.source)
    ? (current.sources as ChartOptionOverlaySource[])
    : [...(current?.sources ?? []), leg.source]

  overlays.set(key, {
    type: 'option-strike',
    key,
    ticker: leg.ticker,
    expiration,
    right: leg.right,
    strike: leg.strike,
    signedQuantity,
    sources,
    label: optionOverlayLabel(signedQuantity, leg.right),
  })
}

function optionOverlayKey(
  leg: Pick<DraftOptionLeg, 'ticker' | 'expiration' | 'right' | 'strike'>,
) {
  return [
    'option-strike',
    leg.ticker.toUpperCase(),
    normalizeExpiration(leg.expiration),
    leg.right,
    leg.strike,
  ].join(':')
}

function normalizeExpiration(expiration: string) {
  return expiration.replaceAll('-', '')
}

function stockCostBasisPrice(position: PortfolioPosition) {
  if (position.average_price !== null && position.average_price > 0) {
    return position.average_price
  }
  if (
    position.cost_basis !== null &&
    position.quantity !== 0 &&
    Number.isFinite(position.cost_basis)
  ) {
    return Math.abs(position.cost_basis / position.quantity)
  }
  return null
}

function optionOverlayLabel(quantity: number, right: OptionRight) {
  const sign = quantity > 0 ? '+' : ''
  return `${sign}${formatQuantity(quantity)} ${right.toLowerCase()}`
}

function formatQuantity(quantity: number) {
  return Number.isInteger(quantity) ? quantity.toFixed(0) : String(quantity)
}
