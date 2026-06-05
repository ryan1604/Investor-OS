import { useMemo, useState } from 'react'

import { LoaderCircle, Save, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import {
  amendOrder,
  cancelOrder,
  type OrderRecord,
  type OrderTimeInForce,
} from '@/api/orders'
import { Alert } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  orderErrorMessage,
  parsePositiveNumber,
} from '@/features/orders/lib/orderEntryUtils'

const ACTIVE_STATUSES = new Set(['submitted', 'working', 'partially_filled'])
const HISTORY_STATUSES = new Set(['filled', 'cancelled', 'rejected'])

type OrdersPageProps = {
  orders: OrderRecord[]
}

type DraftEdit = {
  limitPrice: string
  takeProfitPrice: string
  stopLossPrice: string
  timeInForce: OrderTimeInForce
}

export function OrdersPage({ orders }: OrdersPageProps) {
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null)
  const [draftEdit, setDraftEdit] = useState<DraftEdit | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null)
  const openOrders = useMemo(
    () => orders.filter((order) => ACTIVE_STATUSES.has(order.status)),
    [orders],
  )
  const historyOrders = useMemo(
    () =>
      orders.filter(
        (order) =>
          HISTORY_STATUSES.has(order.status) && isToday(order.updated_at),
      ),
    [orders],
  )

  function beginEdit(order: OrderRecord) {
    const request = order.preview.request
    setEditingOrderId(order.order_id)
    setDraftEdit({
      limitPrice: request.limit_price?.toString() ?? '',
      takeProfitPrice:
        request.order_kind === 'option_strategy'
          ? request.take_profit_price?.toString() ?? ''
          : '',
      stopLossPrice:
        request.order_kind === 'option_strategy'
          ? request.stop_loss_price?.toString() ?? ''
          : '',
      timeInForce: request.time_in_force ?? 'DAY',
    })
    setError(null)
  }

  async function handleCancel(order: OrderRecord) {
    setBusyOrderId(order.order_id)
    setError(null)
    try {
      const response = await cancelOrder(order.order_id, { account: order.account })
      toast.success(response.message)
    } catch (requestError) {
      setError(orderErrorMessage(requestError))
    } finally {
      setBusyOrderId(null)
    }
  }

  async function handleSave(order: OrderRecord) {
    if (!draftEdit) {
      return
    }

    setBusyOrderId(order.order_id)
    setError(null)
    try {
      const response = await amendOrder(order.order_id, {
        account: order.account,
        limit_price: parsePositiveNumber(draftEdit.limitPrice),
        take_profit_price: parsePositiveNumber(draftEdit.takeProfitPrice),
        stop_loss_price: parsePositiveNumber(draftEdit.stopLossPrice),
        time_in_force: draftEdit.timeInForce,
      })
      toast.success(response.message)
      setEditingOrderId(null)
      setDraftEdit(null)
    } catch (requestError) {
      setError(orderErrorMessage(requestError))
    } finally {
      setBusyOrderId(null)
    }
  }

  return (
    <main className="flex min-w-0 w-full flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Orders
        </h1>
        <p className="text-sm text-muted-foreground">
          Active IB orders and current-day terminal history.
        </p>
      </header>

      {error ? <Alert variant="destructive">{error}</Alert> : null}

      <OrderSection
        busyOrderId={busyOrderId}
        draftEdit={draftEdit}
        editingOrderId={editingOrderId}
        emptyMessage="No open orders."
        orders={openOrders}
        title="Open"
        onCancel={handleCancel}
        onDraftEditChange={setDraftEdit}
        onEdit={beginEdit}
        onSave={handleSave}
        onStopEdit={() => {
          setEditingOrderId(null)
          setDraftEdit(null)
        }}
      />

      <OrderSection
        busyOrderId={busyOrderId}
        draftEdit={draftEdit}
        editingOrderId={editingOrderId}
        emptyMessage="No current-day order history."
        history
        orders={historyOrders}
        title="History"
        onCancel={handleCancel}
        onDraftEditChange={setDraftEdit}
        onEdit={beginEdit}
        onSave={handleSave}
        onStopEdit={() => {
          setEditingOrderId(null)
          setDraftEdit(null)
        }}
      />
    </main>
  )
}

function OrderSection({
  busyOrderId,
  draftEdit,
  editingOrderId,
  emptyMessage,
  history = false,
  orders,
  title,
  onCancel,
  onDraftEditChange,
  onEdit,
  onSave,
  onStopEdit,
}: {
  busyOrderId: number | null
  draftEdit: DraftEdit | null
  editingOrderId: number | null
  emptyMessage: string
  history?: boolean
  orders: OrderRecord[]
  title: string
  onCancel: (order: OrderRecord) => void
  onDraftEditChange: (draft: DraftEdit) => void
  onEdit: (order: OrderRecord) => void
  onSave: (order: OrderRecord) => void
  onStopEdit: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {orders.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Order</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Filled</TableHead>
                <TableHead>Editable fields</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.map((order) => (
                <OrderRow
                  busyOrderId={busyOrderId}
                  draftEdit={draftEdit}
                  editingOrderId={editingOrderId}
                  history={history}
                  key={order.order_id}
                  order={order}
                  onCancel={onCancel}
                  onDraftEditChange={onDraftEditChange}
                  onEdit={onEdit}
                  onSave={onSave}
                  onStopEdit={onStopEdit}
                />
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="py-8 text-sm text-muted-foreground">{emptyMessage}</div>
        )}
      </CardContent>
    </Card>
  )
}

function OrderRow({
  busyOrderId,
  draftEdit,
  editingOrderId,
  history,
  order,
  onCancel,
  onDraftEditChange,
  onEdit,
  onSave,
  onStopEdit,
}: {
  busyOrderId: number | null
  draftEdit: DraftEdit | null
  editingOrderId: number | null
  history: boolean
  order: OrderRecord
  onCancel: (order: OrderRecord) => void
  onDraftEditChange: (draft: DraftEdit) => void
  onEdit: (order: OrderRecord) => void
  onSave: (order: OrderRecord) => void
  onStopEdit: () => void
}) {
  const isEditing = editingOrderId === order.order_id && draftEdit !== null
  const isBusy = busyOrderId === order.order_id
  const canEdit = order.editable !== false

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">#{order.order_id}</div>
        <div className="max-w-md truncate text-xs text-muted-foreground">
          {order.preview.summary}
        </div>
        {order.parent_order_id ? (
          <div className="text-xs text-muted-foreground">
            Child of #{order.parent_order_id}
          </div>
        ) : null}
      </TableCell>
      <TableCell className="capitalize">{order.status.replace('_', ' ')}</TableCell>
      <TableCell className="tabular-nums">
        {formatQuantity(order.filled)}
        {order.remaining !== null
          ? ` / ${formatQuantity(order.filled + order.remaining)}`
          : ''}
      </TableCell>
      <TableCell>
        {isEditing ? (
          <OrderEditFields
            draft={draftEdit}
            order={order}
            onChange={onDraftEditChange}
          />
        ) : (
          <EditableSummary order={order} />
        )}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-2">
          {history ? null : isEditing ? (
            <>
              <Button
                aria-label={`Save order ${order.order_id}`}
                size="sm"
                type="button"
                disabled={isBusy}
                onClick={() => onSave(order)}
                className="cursor-pointer active:cursor-pointer"
              >
                {isBusy ? (
                  <LoaderCircle className="animate-spin" data-icon="inline-start" />
                ) : (
                  <Save data-icon="inline-start" />
                )}
                Save
              </Button>
              <Button
                aria-label={`Stop editing order ${order.order_id}`}
                size="sm"
                variant="outline"
                type="button"
                disabled={isBusy}
                onClick={onStopEdit}
                className="cursor-pointer active:cursor-pointer"
              >
                Cancel edit
              </Button>
            </>
          ) : (
            <>
              {canEdit ? (
                <Button
                  size="sm"
                  variant="outline"
                  type="button"
                  onClick={() => onEdit(order)}
                  className="cursor-pointer active:cursor-pointer"
                >
                  Edit
                </Button>
              ) : null}
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    size="sm"
                    variant="destructive"
                    type="button"
                    disabled={isBusy || !order.account}
                    className="cursor-pointer active:cursor-pointer disabled:cursor-not-allowed"
                  >
                    {isBusy ? (
                      <LoaderCircle
                        className="animate-spin"
                        data-icon="inline-start"
                      />
                    ) : (
                      <XCircle data-icon="inline-start" />
                    )}
                    Cancel
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Cancel order #{order.order_id}?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This sends a cancellation request to Interactive Brokers.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Keep order</AlertDialogCancel>
                    <AlertDialogAction onClick={() => onCancel(order)}>
                      Cancel order
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

function OrderEditFields({
  draft,
  order,
  onChange,
}: {
  draft: DraftEdit
  order: OrderRecord
  onChange: (draft: DraftEdit) => void
}) {
  const request = order.preview.request
  return (
    <div className="grid min-w-[18rem] gap-2 sm:grid-cols-2">
      <Field>
        <FieldLabel className="sr-only">Limit price</FieldLabel>
        <Input
          aria-label={`Limit price ${order.order_id}`}
          placeholder="Limit"
          type="number"
          step="0.01"
          value={draft.limitPrice}
          onChange={(event) =>
            onChange({ ...draft, limitPrice: event.target.value })
          }
        />
      </Field>
      <Field>
        <FieldLabel className="sr-only">Time in force</FieldLabel>
        <Select
          value={draft.timeInForce}
          onValueChange={(value) =>
            onChange({
              ...draft,
              timeInForce: value as OrderTimeInForce,
            })
          }
        >
          <SelectTrigger
            aria-label={`Time in force ${order.order_id}`}
            className="w-full"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="DAY">DAY</SelectItem>
            <SelectItem value="GTC">GTC</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      {request.order_kind === 'option_strategy' ? (
        <>
          <Field>
            <FieldLabel className="sr-only">Take profit</FieldLabel>
            <Input
              aria-label={`Take profit ${order.order_id}`}
              placeholder="Take profit"
              type="number"
              step="0.01"
              value={draft.takeProfitPrice}
              onChange={(event) =>
                onChange({ ...draft, takeProfitPrice: event.target.value })
              }
            />
          </Field>
          <Field>
            <FieldLabel className="sr-only">Stop loss</FieldLabel>
            <Input
              aria-label={`Stop loss ${order.order_id}`}
              placeholder="Stop loss"
              type="number"
              step="0.01"
              value={draft.stopLossPrice}
              onChange={(event) =>
                onChange({ ...draft, stopLossPrice: event.target.value })
              }
            />
          </Field>
        </>
      ) : null}
    </div>
  )
}

function EditableSummary({ order }: { order: OrderRecord }) {
  const request = order.preview.request
  if (order.editable === false) {
    return (
      <span className="text-sm text-muted-foreground">
        Reconciled from IB, not editable
      </span>
    )
  }

  const values = [
    request.limit_price !== undefined && request.limit_price !== null
      ? `Limit ${request.limit_price.toFixed(2)}`
      : null,
    request.order_kind === 'option_strategy' && request.take_profit_price
      ? `TP ${request.take_profit_price.toFixed(2)}`
      : null,
    request.order_kind === 'option_strategy' && request.stop_loss_price
      ? `SL ${request.stop_loss_price.toFixed(2)}`
      : null,
    `TIF ${request.time_in_force ?? 'DAY'}`,
  ].filter(Boolean)

  return <span className="text-sm text-muted-foreground">{values.join(' | ')}</span>
}

function formatQuantity(value: number) {
  return Number.isInteger(value) ? value.toFixed(0) : value.toString()
}

function isToday(value: string) {
  const date = new Date(value)
  const now = new Date()
  return date.toDateString() === now.toDateString()
}
