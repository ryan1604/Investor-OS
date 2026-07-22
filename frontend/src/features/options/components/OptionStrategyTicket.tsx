import { useEffect, useMemo, useState } from 'react'

import { Trash2 } from 'lucide-react'

import type { PortfolioResponse } from '@/api/portfolio'
import {
  type OptionStrategyOrderRequest,
  type OrderPreviewResponse,
  type OrderTimeInForce,
} from '@/api/orders'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  ConfirmationPreview,
  PreviewRow,
  SelectField,
} from '@/features/orders/lib/orderEntry'
import { useOrderTicketFlow } from '@/features/orders/lib/orderTicketFlow'
import {
  orderErrorMessage,
  parseSignedNumber,
} from '@/features/orders/lib/orderEntryUtils'
import {
  OrderTicketFooter,
  ReadOnlyTicketAccount,
} from '@/features/options/components/OrderTicketParts'
import type { DraftOptionLeg } from '@/features/options/lib/strategyLegs'
import { formatOptionalPrice } from '@/lib/format'

type OptionStrategyTicketProps = {
  legs: DraftOptionLeg[]
  open: boolean
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
  creditEntry?: boolean
  selectedAccountOnly?: boolean
  warning?: string | null
  onLegsChange: (legs: DraftOptionLeg[]) => void
  onOpenChange: (open: boolean) => void
}

export function OptionStrategyTicket({
  legs,
  open,
  selectedAccount,
  creditEntry = false,
  warning = null,
  onLegsChange,
  onOpenChange,
}: OptionStrategyTicketProps) {
  const account = selectedAccount ?? ''
  const defaultNetPrice = useMemo(() => netStrategyPrice(legs), [legs])
  const [limitPrice, setLimitPrice] = useState(
    formatDisplayedNetPrice(defaultNetPrice, creditEntry),
  )
  const [takeProfitEnabled, setTakeProfitEnabled] = useState(false)
  const [takeProfitPrice, setTakeProfitPrice] = useState('')
  const [stopLossEnabled, setStopLossEnabled] = useState(false)
  const [stopLossPrice, setStopLossPrice] = useState('')
  const [timeInForce, setTimeInForce] = useState<OrderTimeInForce>('DAY')
  const ticket = useOrderTicketFlow(orderErrorMessage)
  const displayedLimitPrice = parseSignedNumber(limitPrice)
  const parsedLimitPrice =
    creditEntry && displayedLimitPrice !== null
      ? -Math.abs(displayedLimitPrice)
      : displayedLimitPrice
  const parsedTakeProfitPrice = takeProfitEnabled
    ? parseSignedNumber(takeProfitPrice)
    : null
  const parsedStopLossPrice = stopLossEnabled ? parseSignedNumber(stopLossPrice) : null
  const request = buildRequest(
    legs,
    account,
    parsedLimitPrice,
    timeInForce,
    takeProfitEnabled ? parsedTakeProfitPrice : null,
    stopLossEnabled ? parsedStopLossPrice : null,
  )
  const validationError = validateDraft(
    legs,
    account,
    parsedLimitPrice,
    creditEntry,
    displayedLimitPrice,
    takeProfitEnabled,
    parsedTakeProfitPrice,
    stopLossEnabled,
    parsedStopLossPrice,
  )

  useEffect(() => {
    if (!open && ticket.step === 'draft') {
      // Keep the closed draft price aligned with selected legs without overriding open edits.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLimitPrice(formatDisplayedNetPrice(defaultNetPrice, creditEntry))
    }
  }, [creditEntry, defaultNetPrice, open, ticket.step])

  function dismissTicket() {
    ticket.resetTicketState()
    onOpenChange(false)
  }

  function closeAndClearTicket() {
    ticket.resetTicketState()
    onOpenChange(false)
    onLegsChange([])
  }

  function updateSignedQuantity(index: number, value: string) {
    const parsedValue = Number(value)
    if (!Number.isInteger(parsedValue)) {
      return
    }

    onLegsChange(
      legs
        .map((leg, legIndex) =>
          legIndex === index ? { ...leg, signedQuantity: parsedValue } : leg,
        )
        .filter((leg) => leg.signedQuantity !== 0),
    )
  }

  async function handleReview() {
    if (validationError) {
      return
    }
    await ticket.review(request)
  }

  async function handleTransmit() {
    await ticket.transmit()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) {
          onOpenChange(true)
        } else {
          dismissTicket()
        }
      }}
    >
      <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Option strategy</DialogTitle>
          <DialogDescription>{strategyTone(parsedLimitPrice)}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {ticket.error ? (
            <Alert variant="destructive">{ticket.error}</Alert>
          ) : null}
          {warning ? <Alert>{warning}</Alert> : null}

          {ticket.step !== 'draft' && ticket.preview ? (
            <StrategyConfirmationPreview preview={ticket.preview} />
          ) : (
            <div className="grid gap-4">
              <ReadOnlyTicketAccount account={account} label="Strategy account" />

              <div className="overflow-hidden rounded-lg border">
                <Table className="w-full text-sm">
                  <TableHeader className="bg-muted/50 text-xs text-muted-foreground">
                    <TableRow>
                      <TableHead className="text-left">Leg</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Bid</TableHead>
                      <TableHead className="text-right">Ask</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {legs.map((leg, index) => (
                      <TableRow key={legKey(leg)}>
                        <TableCell>
                          <div className="font-medium">
                            {leg.ticker} {leg.expiration} {leg.strike}{' '}
                            {leg.right.toLowerCase()}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {leg.signedQuantity > 0 ? 'Buy' : 'Sell'}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Input
                            aria-label={`Quantity ${leg.strike} ${leg.right}`}
                            className="ml-auto w-20 text-right"
                            step="1"
                            type="number"
                            value={leg.signedQuantity}
                            onChange={(event) =>
                              updateSignedQuantity(index, event.target.value)
                            }
                          />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatOptionalPrice(leg.bid)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatOptionalPrice(leg.ask)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() =>
                              onLegsChange(
                                legs.filter((_, legIndex) => legIndex !== index),
                              )
                            }
                            className="cursor-pointer active:cursor-pointer"
                          >
                            <Trash2 />
                            <span className="sr-only">Remove leg</span>
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <Field>
                <FieldLabel>
                  {creditEntry ? 'Net limit credit' : 'Net limit price'}
                </FieldLabel>
                <Input
                  aria-label={creditEntry ? 'Net limit credit' : 'Net limit price'}
                  min={creditEntry ? '0.01' : undefined}
                  step="0.01"
                  type="number"
                  value={limitPrice}
                  onChange={(event) => setLimitPrice(event.target.value)}
                />
              </Field>

              <div className="grid gap-2 rounded-lg border bg-muted/30 p-3">
                <ExitPriceField
                  checked={takeProfitEnabled}
                  label="Take profit"
                  price={takeProfitPrice}
                  priceLabel="Take profit price"
                  onCheckedChange={setTakeProfitEnabled}
                  onPriceChange={setTakeProfitPrice}
                />
                <ExitPriceField
                  checked={stopLossEnabled}
                  label="Stop loss"
                  price={stopLossPrice}
                  priceLabel="Stop loss price"
                  onCheckedChange={setStopLossEnabled}
                  onPriceChange={setStopLossPrice}
                />
              </div>

              <SelectField
                label="Strategy time in force"
                value={timeInForce}
                onValueChange={(value) =>
                  setTimeInForce(value as OrderTimeInForce)
                }
                options={[
                  { label: 'DAY', value: 'DAY' },
                  { label: 'GTC', value: 'GTC' },
                ]}
              />

              {validationError ? (
                <Alert variant="destructive">{validationError}</Alert>
              ) : null}
            </div>
          )}
        </div>

        <OrderTicketFooter
          step={ticket.step}
          isSubmitting={ticket.isSubmitting}
          reviewDisabled={Boolean(validationError)}
          onClose={closeAndClearTicket}
          onEdit={() => ticket.setStep('draft')}
          onReview={() => void handleReview()}
          onTransmit={() => void handleTransmit()}
        />
      </DialogContent>
    </Dialog>
  )
}

function ExitPriceField({
  checked,
  label,
  price,
  priceLabel,
  onCheckedChange,
  onPriceChange,
}: {
  checked: boolean
  label: string
  price: string
  priceLabel: string
  onCheckedChange: (checked: boolean) => void
  onPriceChange: (price: string) => void
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8rem] sm:items-center">
      <FieldLabel className="flex min-w-0 items-center gap-2">
        <Checkbox
          aria-label={label}
          checked={checked}
          onCheckedChange={(value) => onCheckedChange(value === true)}
        />
        <span>{label}</span>
      </FieldLabel>
      <Input
        aria-label={priceLabel}
        disabled={!checked}
        min="0"
        step="0.01"
        type="number"
        value={price}
        onChange={(event) => onPriceChange(event.target.value)}
      />
    </div>
  )
}

function StrategyConfirmationPreview({ preview }: { preview: OrderPreviewResponse }) {
  const request = preview.request
  return (
    <ConfirmationPreview preview={preview} summaryLabel="Strategy">
      {request.order_kind === 'option_strategy' &&
      request.take_profit_price ? (
        <PreviewRow
          label="Take profit"
          value={formatOptionalPrice(request.take_profit_price)}
        />
      ) : null}
      {request.order_kind === 'option_strategy' && request.stop_loss_price ? (
        <PreviewRow
          label="Stop loss"
          value={formatOptionalPrice(request.stop_loss_price)}
        />
      ) : null}
    </ConfirmationPreview>
  )
}

function buildRequest(
  legs: DraftOptionLeg[],
  account: string,
  limitPrice: number | null,
  timeInForce: OrderTimeInForce,
  takeProfitPrice: number | null,
  stopLossPrice: number | null,
): OptionStrategyOrderRequest | null {
  if (!account || limitPrice === null || !legs.length) {
    return null
  }

  return {
    order_kind: 'option_strategy',
    account,
    limit_price: limitPrice,
    ...(takeProfitPrice !== null ? { take_profit_price: takeProfitPrice } : {}),
    ...(stopLossPrice !== null ? { stop_loss_price: stopLossPrice } : {}),
    time_in_force: timeInForce,
    legs: legs.map((leg) => ({
      ticker: leg.ticker,
      expiration: leg.expiration,
      right: leg.right,
      strike: leg.strike,
      action: leg.signedQuantity > 0 ? 'BUY' : 'SELL',
      quantity: Math.abs(leg.signedQuantity),
    })),
  }
}

function validateDraft(
  legs: DraftOptionLeg[],
  account: string,
  limitPrice: number | null,
  creditEntry: boolean,
  displayedLimitPrice: number | null,
  takeProfitEnabled: boolean,
  takeProfitPrice: number | null,
  stopLossEnabled: boolean,
  stopLossPrice: number | null,
) {
  if (!account) {
    return 'Select an account.'
  }
  if (!legs.length) {
    return 'Add at least one option leg.'
  }
  if (legs.some((leg) => leg.signedQuantity === 0)) {
    return 'Remove zero-quantity legs.'
  }
  if (limitPrice === null) {
    return 'Enter a net limit price.'
  }
  if (creditEntry && displayedLimitPrice !== null && displayedLimitPrice <= 0) {
    return 'Net limit credit must be greater than zero.'
  }
  if (takeProfitEnabled && takeProfitPrice === null) {
    return 'Enter a take profit price.'
  }
  if (takeProfitPrice !== null && takeProfitPrice <= 0) {
    return 'Take profit price must be greater than zero.'
  }
  if (stopLossEnabled && stopLossPrice === null) {
    return 'Enter a stop loss price.'
  }
  if (stopLossPrice !== null && stopLossPrice <= 0) {
    return 'Stop loss price must be greater than zero.'
  }
  return null
}

function netStrategyPrice(legs: DraftOptionLeg[]) {
  return legs.reduce((total, leg) => {
    if (leg.quote === null) {
      return total
    }
    return total + leg.signedQuantity * leg.quote
  }, 0)
}

function formatNetPrice(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : ''
}

function formatDisplayedNetPrice(value: number, creditEntry: boolean) {
  return formatNetPrice(creditEntry ? Math.abs(value) : value)
}

function strategyTone(limitPrice: number | null) {
  if (limitPrice === null || limitPrice === 0) {
    return 'Net even'
  }
  return limitPrice > 0 ? 'Net debit' : 'Net credit'
}

function legKey(leg: DraftOptionLeg) {
  return `${leg.ticker}-${leg.expiration}-${leg.right}-${leg.strike}`
}
