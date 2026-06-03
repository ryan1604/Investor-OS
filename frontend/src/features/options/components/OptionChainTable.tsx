import { useLayoutEffect, useRef } from 'react'

import type {
  OptionChainResponse,
  OptionQuote,
  OptionsAnalysisResponse,
} from '@/api/options'
import { Alert } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatOptionalDecimal,
  formatOptionalInteger,
  formatOptionalPercent,
  formatOptionalPrice,
  signedValueClassName,
} from '@/lib/format'

type OptionChainTableProps = {
  analysis: OptionsAnalysisResponse
  chain: OptionChainResponse | null
  error: string | null
  isLoading: boolean
  selectedExpiration: string
}

type NumericQuoteFieldKey = {
  [Key in keyof OptionQuote]: OptionQuote[Key] extends number | null
    ? Key
    : never
}[keyof OptionQuote]

type QuoteField = {
  key: NumericQuoteFieldKey
  label: string
  format: (value: number | null) => string
  sizeKey?: 'bid_size' | 'ask_size'
  className?: (value: number | null) => string
}

const quoteFields: QuoteField[] = [
  { key: 'delta', label: 'Delta', format: formatOptionalDecimal },
  { key: 'bid', label: 'Bid', format: formatOptionalPrice, sizeKey: 'bid_size' },
  { key: 'ask', label: 'Ask', format: formatOptionalPrice, sizeKey: 'ask_size' },
  { key: 'mid', label: 'Mid', format: formatOptionalPrice },
  { key: 'last', label: 'Last', format: formatOptionalPrice },
  { key: 'close', label: 'Close', format: formatOptionalPrice },
  { key: 'model_price', label: 'Model', format: formatOptionalPrice },
  {
    key: 'change_percent',
    label: 'Chg %',
    format: formatOptionalPercent,
    className: signedValueClassName,
  },
  { key: 'volume', label: 'Vol', format: formatOptionalInteger },
  { key: 'open_interest', label: 'OI', format: formatOptionalInteger },
  { key: 'gamma', label: 'Gamma', format: formatOptionalDecimal },
  { key: 'theta', label: 'Theta', format: formatOptionalDecimal },
  {
    key: 'implied_volatility_percent',
    label: 'IV %',
    format: formatOptionalPercent,
  },
  { key: 'breakeven', label: 'BE', format: formatOptionalPrice },
]
const callQuoteFields = [...quoteFields].reverse()
const quoteColumnWidth = `${100 / quoteFields.length}%`

type ChainDisplayRow =
  | { type: 'quote'; row: NonNullable<OptionChainResponse['rows']>[number] }
  | { type: 'underlying'; key: string }

export function OptionChainTable({
  analysis,
  chain,
  error,
  isLoading,
  selectedExpiration,
}: OptionChainTableProps) {
  const underlyingPrice =
    analysis.underlying_price ?? chain?.underlying_price ?? null
  const callScrollerRef = useRef<HTMLDivElement>(null)
  const putScrollerRef = useRef<HTMLDivElement>(null)
  const isSyncingScrollRef = useRef(false)
  const displayRows = chain?.rows.length
    ? chain.rows.flatMap<ChainDisplayRow>((row, index) => {
        const nextRow = chain.rows[index + 1]
        const shouldShowUnderlyingPrice =
          underlyingPrice !== null &&
          underlyingPrice > row.strike &&
          (!nextRow || underlyingPrice <= nextRow.strike)

        return shouldShowUnderlyingPrice
          ? [
              { type: 'quote', row },
              {
                type: 'underlying',
                key: `${analysis.ticker}-underlying-price`,
              },
            ]
          : [{ type: 'quote', row }]
      })
    : []

  if (
    chain?.rows.length &&
    underlyingPrice !== null &&
    underlyingPrice <= chain.rows[0].strike
  ) {
    displayRows.unshift({
      type: 'underlying',
      key: `${analysis.ticker}-underlying-price`,
    })
  }

  useLayoutEffect(() => {
    const callScroller = callScrollerRef.current
    const putScroller = putScrollerRef.current
    if (!callScroller || !putScroller) {
      return
    }

    putScroller.scrollLeft = 0
    callScroller.scrollLeft = callScroller.scrollWidth - callScroller.clientWidth
  }, [chain?.expiration, displayRows.length])

  function syncScroller(source: 'call' | 'put') {
    if (isSyncingScrollRef.current) {
      return
    }

    const callScroller = callScrollerRef.current
    const putScroller = putScrollerRef.current
    if (!callScroller || !putScroller) {
      return
    }

    isSyncingScrollRef.current = true
    if (source === 'call') {
      putScroller.scrollLeft =
        callScroller.scrollWidth -
        callScroller.clientWidth -
        callScroller.scrollLeft
    } else {
      callScroller.scrollLeft =
        callScroller.scrollWidth -
        callScroller.clientWidth -
        putScroller.scrollLeft
    }
    requestAnimationFrame(() => {
      isSyncingScrollRef.current = false
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
          <span>Chain</span>
          <span className="text-sm font-normal text-muted-foreground">
            {chain?.expiration ?? selectedExpiration}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error ? (
          <Alert variant="destructive" className="mb-4">
            {error}
          </Alert>
        ) : null}

        {isLoading ? (
          <ChainMessage>Loading chain...</ChainMessage>
        ) : chain?.rows.length ? (
          <div className="grid grid-cols-[minmax(0,1fr)_6rem_minmax(0,1fr)]">
            <div
              ref={callScrollerRef}
              className="overflow-x-auto overscroll-x-contain"
              onScroll={() => syncScroller('call')}
            >
              <QuotePane
                fields={callQuoteFields}
                rows={displayRows}
                side="call"
              />
            </div>
            <StrikePane
              rows={displayRows}
              ticker={analysis.ticker}
              underlyingPrice={underlyingPrice}
            />
            <div
              ref={putScrollerRef}
              className="overflow-x-auto overscroll-x-contain"
              onScroll={() => syncScroller('put')}
            >
              <QuotePane fields={quoteFields} rows={displayRows} side="put" />
            </div>
          </div>
        ) : (
          <ChainMessage>No chain rows returned.</ChainMessage>
        )}
      </CardContent>
    </Card>
  )
}

function QuotePane({
  fields,
  rows,
  side,
}: {
  fields: QuoteField[]
  rows: ChainDisplayRow[]
  side: 'call' | 'put'
}) {
  return (
    <table className="w-[1120px] table-fixed text-xs">
      <colgroup>
        {fields.map((field) => (
          <col key={`${side}-${field.key}`} style={{ width: quoteColumnWidth }} />
        ))}
      </colgroup>
      <TableHeader>
        <TableRow>
          <TableHead colSpan={fields.length} className="text-center">
            {side === 'call' ? 'Calls' : 'Puts'}
          </TableHead>
        </TableRow>
        <TableRow>
          {fields.map((field) => (
            <TableHead key={`${side}-${field.key}`} className="text-center">
              <span>{field.label}</span>
              {field.sizeKey ? (
                <span className="block text-[10px] font-normal text-muted-foreground">
                  x Size
                </span>
              ) : null}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((displayRow) =>
          displayRow.type === 'underlying' ? (
            <UnderlyingSpacerRow
              key={`${side}-${displayRow.key}`}
              colSpan={fields.length}
            />
          ) : (
            <TableRow key={`${side}-${displayRow.row.strike}`}>
              {fields.map((field) => (
                <QuoteCell
                  key={`${side}-${displayRow.row.strike}-${field.key}`}
                  field={field}
                  quote={displayRow.row[side]}
                />
              ))}
            </TableRow>
          ),
        )}
      </TableBody>
    </table>
  )
}

function StrikePane({
  rows,
  ticker,
  underlyingPrice,
}: {
  rows: ChainDisplayRow[]
  ticker: string
  underlyingPrice: number | null
}) {
  return (
    <table className="w-24 table-fixed self-start text-xs">
      <TableHeader>
        <TableRow>
          <TableHead className="bg-muted/50 text-center">Strike</TableHead>
        </TableRow>
        <TableRow>
          <TableHead className="bg-muted/50 text-center">Price</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((displayRow) =>
          displayRow.type === 'underlying' ? (
            <TableRow key={displayRow.key} className="hover:bg-transparent">
              <TableCell className="h-10 border-y px-1 py-1.5 text-center text-sm">
                <span className="font-medium">{ticker}</span>
                <span className="text-muted-foreground">: </span>
                <span className="tabular-nums text-emerald-400">
                  {formatOptionalPrice(underlyingPrice)}
                </span>
              </TableCell>
            </TableRow>
          ) : (
            <TableRow key={displayRow.row.strike}>
              <TableCell className="h-14 bg-muted/50 text-center font-medium tabular-nums">
                {formatOptionalPrice(displayRow.row.strike)}
              </TableCell>
            </TableRow>
          ),
        )}
      </TableBody>
    </table>
  )
}

function UnderlyingSpacerRow({ colSpan }: { colSpan: number }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={colSpan} className="h-10 border-y px-3 py-1.5 text-sm">
        &nbsp;
      </TableCell>
    </TableRow>
  )
}

function ChainMessage({ children }: { children: string }) {
  return (
    <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}

function QuoteCell({
  field,
  quote,
}: {
  field: QuoteField
  quote: OptionQuote | null
}) {
  const value = quote ? quote[field.key] : null
  const size = field.sizeKey && quote ? quote[field.sizeKey] : null

  return (
    <TableCell
      className={[
        'h-14 text-center tabular-nums',
        field.className ? field.className(value).replace('text-right', '') : '',
      ].join(' ')}
    >
      <span className="block">{field.format(value)}</span>
      {field.sizeKey ? (
        <span className="block text-[10px] text-muted-foreground">
          {size === null ? '-' : `x${formatOptionalInteger(size)}`}
        </span>
      ) : null}
    </TableCell>
  )
}
