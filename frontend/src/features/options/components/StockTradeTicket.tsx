import { useMemo, useState } from 'react'

import { LoaderCircle, Send, Ticket } from 'lucide-react'
import { toast } from 'sonner'

import type { PortfolioPosition, PortfolioResponse } from '@/api/portfolio'
import {
  previewOrder,
  transmitOrder,
  type OrderAction,
  type OrderPreviewResponse,
  type OrderTimeInForce,
  type OrderType,
  type StockOrderRequest,
} from '@/api/orders'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  ConfirmationPreview,
  PreviewRow,
  SelectField,
} from '@/features/orders/lib/orderEntry'
import {
  accountOptions,
  orderErrorMessage,
  parsePositiveInteger,
  parsePositiveNumber,
  portfolioAccounts,
} from '@/features/orders/lib/orderEntryUtils'
import { formatOptionalPrice } from '@/lib/format'

type StockTradeTicketProps = {
  ticker: string
  latestPrice: number | null
  portfolio: PortfolioResponse | null
  selectedAccount: string | null
}

type TicketStep = 'draft' | 'confirm' | 'submitted'

export function StockTradeTicket({
  ticker,
  latestPrice,
  portfolio,
  selectedAccount,
}: StockTradeTicketProps) {
  const accounts = useMemo(() => portfolioAccounts(portfolio), [portfolio])
  const defaultAccount =
    selectedAccount && accounts.includes(selectedAccount)
      ? selectedAccount
      : accounts[0] ?? ''
  const [open, setOpen] = useState(false)
  const [account, setAccount] = useState(defaultAccount)
  const [action, setAction] = useState<OrderAction>('BUY')
  const [quantity, setQuantity] = useState('1')
  const [orderType, setOrderType] = useState<OrderType>('MARKET')
  const [limitPrice, setLimitPrice] = useState('')
  const [timeInForce, setTimeInForce] = useState<OrderTimeInForce>('DAY')
  const [step, setStep] = useState<TicketStep>('draft')
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const ownedShares = ownedStockShares(portfolio?.positions ?? [], account, ticker)
  const request = buildRequest({
    account,
    action,
    ticker,
    quantity,
    orderType,
    limitPrice,
    timeInForce,
  })
  const validationError = validateDraft({
    account,
    action,
    quantity,
    orderType,
    limitPrice,
    ownedShares,
  })

  function resetDraft(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) {
      setStep('draft')
      setPreview(null)
      setError(null)
      setIsSubmitting(false)
    } else {
      setAccount(defaultAccount)
    }
  }

  async function handleReview() {
    if (!request || validationError) {
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      setPreview(await previewOrder(request))
      setStep('confirm')
    } catch (requestError) {
      setError(orderErrorMessage(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleTransmit() {
    if (!preview) {
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      const response = await transmitOrder(preview.request)
      toast.success(response.message)
      setStep('submitted')
    } catch (requestError) {
      setError(orderErrorMessage(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        className="cursor-pointer active:cursor-pointer"
        onClick={() => resetDraft(true)}
      >
        <Ticket data-icon="inline-start" />
        Trade
      </Button>

      <Sheet open={open} onOpenChange={resetDraft}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Trade {ticker}</SheetTitle>
            <SheetDescription>
              Last {formatOptionalPrice(latestPrice)}
            </SheetDescription>
          </SheetHeader>

          <div className="flex flex-col gap-4 px-4">
            {error ? <Alert variant="destructive">{error}</Alert> : null}

            {step !== 'draft' && preview ? (
              <StockConfirmationPreview preview={preview} />
            ) : (
              <div className="grid gap-4">
                <SelectField
                  label="Account"
                  value={account}
                  onValueChange={setAccount}
                  options={accountOptions(portfolio)}
                />

                <Field>
                  <FieldLabel>Action</FieldLabel>
                  <ButtonGroup className="grid grid-cols-2">
                    {(['BUY', 'SELL'] as const).map((nextAction) => (
                      <Button
                        key={nextAction}
                        type="button"
                        variant={action === nextAction ? 'default' : 'outline'}
                        onClick={() => setAction(nextAction)}
                        className="cursor-pointer active:cursor-pointer"
                      >
                        {nextAction === 'BUY' ? 'Buy' : 'Sell'}
                      </Button>
                    ))}
                  </ButtonGroup>
                </Field>

                <Field>
                  <FieldLabel>Shares</FieldLabel>
                  <Input
                    aria-label="Shares"
                    min="0"
                    step="1"
                    type="number"
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                  />
                </Field>

                <SelectField
                  label="Order type"
                  value={orderType}
                  onValueChange={(value) => setOrderType(value as OrderType)}
                  options={[
                    { label: 'Market', value: 'MARKET' },
                    { label: 'Limit', value: 'LIMIT' },
                  ]}
                />

                {orderType === 'LIMIT' ? (
                  <Field>
                    <FieldLabel>Limit price</FieldLabel>
                    <Input
                      aria-label="Limit price"
                      min="0"
                      step="0.01"
                      type="number"
                      value={limitPrice}
                      onChange={(event) => setLimitPrice(event.target.value)}
                    />
                  </Field>
                ) : null}

                <SelectField
                  label="Time in force"
                  value={timeInForce}
                  onValueChange={(value) =>
                    setTimeInForce(value as OrderTimeInForce)
                  }
                  options={[
                    { label: 'DAY', value: 'DAY' },
                    { label: 'GTC', value: 'GTC' },
                  ]}
                />

                <div className="rounded-lg border bg-muted/30 p-3 text-sm">
                  <div className="flex justify-between gap-3">
                    <span className="text-muted-foreground">Owned</span>
                    <span className="tabular-nums">{ownedShares}</span>
                  </div>
                </div>

                {validationError ? (
                  <Alert variant="destructive">{validationError}</Alert>
                ) : null}
              </div>
            )}
          </div>

          <SheetFooter>
            {step === 'submitted' ? (
              <Button
                type="button"
                onClick={() => resetDraft(false)}
                className="cursor-pointer active:cursor-pointer"
              >
                Close
              </Button>
            ) : step === 'confirm' ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setStep('draft')}
                  disabled={isSubmitting}
                  className="cursor-pointer active:cursor-pointer"
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  onClick={() => void handleTransmit()}
                  disabled={isSubmitting}
                  className="cursor-pointer active:cursor-pointer"
                >
                  {isSubmitting ? (
                    <LoaderCircle
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <Send data-icon="inline-start" />
                  )}
                  Transmit
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => resetDraft(false)}
                  disabled={isSubmitting}
                  className="cursor-pointer active:cursor-pointer"
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  onClick={() => void handleReview()}
                  disabled={Boolean(validationError) || isSubmitting}
                  className="cursor-pointer active:cursor-pointer disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <LoaderCircle
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : null}
                  Review
                </Button>
              </>
            )}
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  )
}

function StockConfirmationPreview({ preview }: { preview: OrderPreviewResponse }) {
  const request = preview.request

  return (
    <ConfirmationPreview preview={preview} summaryLabel="Order">
      {request.order_kind === 'stock' && request.limit_price ? (
        <PreviewRow label="Limit" value={formatOptionalPrice(request.limit_price)} />
      ) : null}
    </ConfirmationPreview>
  )
}

function ownedStockShares(
  positions: PortfolioPosition[],
  account: string,
  ticker: string,
) {
  return positions
    .filter(
      (position) =>
        position.account === account &&
        position.symbol.toUpperCase() === ticker.toUpperCase() &&
        position.sec_type === 'STK',
    )
    .reduce((total, position) => total + Math.max(position.quantity, 0), 0)
}

function buildRequest({
  account,
  action,
  ticker,
  quantity,
  orderType,
  limitPrice,
  timeInForce,
}: {
  account: string
  action: OrderAction
  ticker: string
  quantity: string
  orderType: OrderType
  limitPrice: string
  timeInForce: OrderTimeInForce
}): StockOrderRequest | null {
  const shareQuantity = parsePositiveInteger(quantity)
  const parsedLimitPrice = parsePositiveNumber(limitPrice)

  if (!account || shareQuantity === null) {
    return null
  }

  if (orderType === 'LIMIT' && parsedLimitPrice === null) {
    return null
  }

  return {
    order_kind: 'stock',
    account,
    ticker,
    action,
    quantity: shareQuantity,
    order_type: orderType,
    limit_price: orderType === 'LIMIT' ? parsedLimitPrice : null,
    time_in_force: timeInForce,
  }
}

function validateDraft(
  {
    account,
    action,
    quantity,
    orderType,
    limitPrice,
    ownedShares,
  }: {
    account: string
    action: OrderAction
    quantity: string
    orderType: OrderType
    limitPrice: string
    ownedShares: number
  },
) {
  const shareQuantity = parsePositiveInteger(quantity)

  if (!account) {
    return 'Select an account.'
  }
  if (shareQuantity === null) {
    return 'Enter a whole share quantity.'
  }
  if (orderType === 'LIMIT' && parsePositiveNumber(limitPrice) === null) {
    return 'Enter a limit price.'
  }
  if (action === 'SELL' && shareQuantity > ownedShares) {
    return 'Sell quantity exceeds selected-account shares.'
  }
  return null
}
