import { memo, useLayoutEffect, useMemo, useRef } from 'react'

import type {
  OptionChainResponse,
  OptionQuote,
  OptionsAnalysisResponse,
} from '@/api/options'
import type { OptionQuoteSelection } from '@/features/options/lib/strategyLegs'
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
import { optionReturnPercent } from '@/features/options/lib/optionReturns'

type OptionChainTableProps = {
  analysis: OptionsAnalysisResponse
  chain: OptionChainResponse | null
  error: string | null
  isLoading: boolean
  onQuoteClick?: (selection: OptionQuoteSelection) => void
  selectedExpiration: string
}

type NumericQuoteFieldKey = {
  [Key in keyof OptionQuote]: OptionQuote[Key] extends number | null
    ? Key
    : never
}[keyof OptionQuote]

type QuoteField = {
  key: NumericQuoteFieldKey | 'return_percent'
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
  { key: 'return_percent', label: 'Return %', format: formatOptionalPercent },
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
  onQuoteClick,
  selectedExpiration,
}: OptionChainTableProps) {
  const underlyingPrice =
    analysis.underlying_price ?? chain?.underlying_price ?? null
  const callScrollerRef = useRef<HTMLDivElement>(null)
  const putScrollerRef = useRef<HTMLDivElement>(null)
  const isSyncingScrollRef = useRef(false)
  const displayRows = useMemo(
    () => buildDisplayRows(chain, analysis.ticker, underlyingPrice),
    [analysis.ticker, chain, underlyingPrice],
  )

  useLayoutEffect(() => {
    const callScroller = callScrollerRef.current
    const putScroller = putScrollerRef.current
    if (!callScroller || !putScroller) {
      return
    }

    callScroller.scrollLeft = 0
    putScroller.scrollLeft = 0
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
      putScroller.scrollLeft = Math.abs(callScroller.scrollLeft)
    } else {
      callScroller.scrollLeft = -putScroller.scrollLeft
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
        {!error && chain?.warning ? (
          <Alert className="mb-4">{chain.warning}</Alert>
        ) : null}

        {isLoading ? (
          <ChainMessage>Loading chain...</ChainMessage>
        ) : chain?.rows.length ? (
          <div className="grid grid-cols-[minmax(0,1fr)_6rem_minmax(0,1fr)]">
            <div
              ref={callScrollerRef}
              dir="rtl"
              className="overflow-x-auto overscroll-x-contain"
              onScroll={() => syncScroller('call')}
            >
              <QuotePane
                fields={callQuoteFields}
                rows={displayRows}
                side="call"
                ticker={analysis.ticker}
                expiration={chain.expiration}
                underlyingPrice={underlyingPrice}
                onQuoteClick={onQuoteClick}
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
              <QuotePane
                fields={quoteFields}
                rows={displayRows}
                side="put"
                ticker={analysis.ticker}
                expiration={chain.expiration}
                underlyingPrice={underlyingPrice}
                onQuoteClick={onQuoteClick}
              />
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
  expiration,
  fields,
  onQuoteClick,
  rows,
  side,
  ticker,
  underlyingPrice,
}: {
  expiration: string
  fields: QuoteField[]
  onQuoteClick?: (selection: OptionQuoteSelection) => void
  rows: ChainDisplayRow[]
  side: 'call' | 'put'
  ticker: string
  underlyingPrice: number | null
}) {
  return (
    <table dir="ltr" className="w-[1120px] table-fixed text-xs">
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
                  expiration={expiration}
                  onQuoteClick={onQuoteClick}
                  quote={displayRow.row[side]}
                  side={side}
                  strike={displayRow.row.strike}
                  ticker={ticker}
                  underlyingPrice={underlyingPrice}
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

const QuoteCell = memo(function QuoteCell({
  expiration,
  field,
  onQuoteClick,
  quote,
  side,
  strike,
  ticker,
  underlyingPrice,
}: {
  expiration: string
  field: QuoteField
  onQuoteClick?: (selection: OptionQuoteSelection) => void
  quote: OptionQuote | null
  side: 'call' | 'put'
  strike: number
  ticker: string
  underlyingPrice: number | null
}) {
  const value =
    field.key === 'return_percent'
      ? optionReturnPercent(side, quote?.mid ?? null, strike, underlyingPrice)
      : quote
        ? quote[field.key]
        : null
  const size = field.sizeKey && quote ? quote[field.sizeKey] : null
  const isInteractiveQuote =
    onQuoteClick !== undefined &&
    quote !== null &&
    value !== null &&
    (field.key === 'bid' || field.key === 'ask')
  const displayValue = field.format(value)

  return (
    <TableCell
      className={[
        'h-14 text-center tabular-nums',
        field.className ? field.className(value).replace('text-right', '') : '',
      ].join(' ')}
    >
      {isInteractiveQuote ? (
        <button
          type="button"
          className="mx-auto block rounded-md px-1.5 py-0.5 text-foreground underline-offset-2 transition hover:bg-muted hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() =>
            onQuoteClick({
              ticker,
              expiration,
              right: side === 'call' ? 'CALL' : 'PUT',
              strike,
              action: field.key === 'ask' ? 'BUY' : 'SELL',
              quote: value,
              bid: quote.bid,
              ask: quote.ask,
            })
          }
        >
          {displayValue}
        </button>
      ) : (
        <span className="block">{displayValue}</span>
      )}
      {field.sizeKey ? (
        <span className="block text-[10px] text-muted-foreground">
          {size === null ? '-' : `x${formatOptionalInteger(size)}`}
        </span>
      ) : null}
    </TableCell>
  )
})

function buildDisplayRows(
  chain: OptionChainResponse | null,
  ticker: string,
  underlyingPrice: number | null,
) {
  if (!chain?.rows.length) {
    return []
  }

  const displayRows = chain.rows.flatMap<ChainDisplayRow>((row, index) => {
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
            key: `${ticker}-underlying-price`,
          },
        ]
      : [{ type: 'quote', row }]
  })

  if (underlyingPrice !== null && underlyingPrice <= chain.rows[0].strike) {
    displayRows.unshift({
      type: 'underlying',
      key: `${ticker}-underlying-price`,
    })
  }

  return displayRows
}
