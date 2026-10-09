import type { NavRow } from '@/api/portfolioNav'

const NAV_RANGES = ['1M', '3M', 'YTD', '1Y', '3Y', '5Y', 'All'] as const
export type NavRange = typeof NAV_RANGES[number]

export function navRangeRows(rows: NavRow[], range: NavRange, today = new Date()) {
  const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))
  const start = new Date(end)
  if (range === 'All') return rows
  if (range === 'YTD') start.setUTCMonth(0, 1)
  else {
    const day = start.getUTCDate()
    start.setUTCDate(1)
    start.setUTCMonth(start.getUTCMonth() - (range === '5Y' ? 60 : range === '3Y' ? 36 : range === '1Y' ? 12 : range === '3M' ? 3 : 1))
    const last = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0)).getUTCDate()
    start.setUTCDate(Math.min(day, last))
  }
  return rows.filter(row => row.report_date >= start.toISOString().slice(0, 10) && row.report_date <= end.toISOString().slice(0, 10))
}

export function currencySegments(rows: NavRow[]) {
  const segments: NavRow[][] = []
  for (const row of rows) {
    if (!segments.length || segments.at(-1)![0].currency !== row.currency) segments.push([])
    segments.at(-1)!.push(row)
  }
  return segments
}

export function navDate(value: string | number) {
  return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value))
}

export function availableNavRanges(rows: NavRow[], today = new Date()) {
  return NAV_RANGES.filter(range => {
    if (range !== '3Y' && range !== '5Y') return true
    const cutoff = new Date(Date.UTC(today.getUTCFullYear() - (range === '3Y' ? 3 : 5), today.getUTCMonth(), today.getUTCDate()))
    return rows.some(row => row.report_date <= cutoff.toISOString().slice(0, 10))
  })
}

export function navPoints(rows: NavRow[], percentage: boolean) {
  const base = Number(rows[0]?.nav)
  if (percentage && !(base > 0)) return []
  return rows.map(row => ({ date: Date.parse(row.report_date), value: percentage ? (Number(row.nav) / base - 1) * 100 : Number(row.nav) }))
}
