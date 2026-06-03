import type { SortKey } from '@/features/portfolio/lib/positions'

export type PositionsTableColumn = {
  label: string
  sortKey: SortKey
  align?: 'left' | 'right'
}

export const POSITIONS_TABLE_COLUMNS: PositionsTableColumn[] = [
  { label: 'Instruments', sortKey: 'instrument' },
  { label: 'Last Price', sortKey: 'last_price', align: 'right' },
  { label: 'Change %', sortKey: 'change_percent', align: 'right' },
  { label: 'P&L', sortKey: 'pnl', align: 'right' },
  { label: 'P&L %', sortKey: 'pnl_percent', align: 'right' },
  { label: 'Unrealized P&L', sortKey: 'unrealized_pnl', align: 'right' },
  {
    label: 'Unrealized P&L %',
    sortKey: 'unrealized_pnl_percent',
    align: 'right',
  },
  { label: 'Market Value', sortKey: 'market_value', align: 'right' },
  { label: 'Positions', sortKey: 'quantity', align: 'right' },
  { label: 'Cost Basis', sortKey: 'cost_basis', align: 'right' },
  { label: 'Average Price', sortKey: 'average_price', align: 'right' },
  { label: '% Net Liquidity', sortKey: 'net_liquidity_percent', align: 'right' },
]
