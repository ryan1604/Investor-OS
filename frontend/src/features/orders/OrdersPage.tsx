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
import { AccountSelector } from '@/features/portfolio/components/AccountSelector'
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
  parsePositiveInteger,
  parsePositiveNumber,
} from '@/features/orders/lib/orderEntryUtils'

type OrdersPageProps = {
  accounts: string[]
  orders: OrderRecord[]
  selectedAccount: string | null
  warning?: string | null
  onSelectedAccountChange: (account: string) => void
}

type DraftEdit = {
  quantity: string
  limitPrice: string
  takeProfitPrice: string
  stopLossPrice: string
  timeInForce: OrderTimeInForce
}

type OrderGroup = {
  groupId: number
  primary: OrderRecord
  children: OrderRecord[]
  records: OrderRecord[]
  readOnlyReason: string | null
}

export function OrdersPage({
  accounts,
  orders,
  selectedAccount,
  warning,
  onSelectedAccountChange,
}: OrdersPageProps) {
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null)
  const [draftEdit, setDraftEdit] = useState<DraftEdit | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null)
  const openOrders = useMemo(
    () =>
      orders.filter(
        (order) => order.is_open && order.account === selectedAccount,
      ),
    [orders, selectedAccount],
  )
  const historyOrders = useMemo(
    () =>
      orders.filter(
        (order) =>
          order.is_current_day_history && order.account === selectedAccount,
      ),
    [orders, selectedAccount],
  )
  const openOrderGroups = useMemo(() => groupOrders(openOrders), [openOrders])
  const historyOrderGroups = useMemo(() => groupOrders(historyOrders), [historyOrders])

  function beginEdit(group: OrderGroup) {
    const order = group.primary
    const request = order.preview.request
    setEditingGroupId(group.groupId)
    setDraftEdit({
      quantity: modeledQuantity(order).toString(),
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

  async function handleSave(group: OrderGroup) {
    if (!draftEdit) {
      return
    }

    const order = group.primary
    const quantity = parsePositiveInteger(draftEdit.quantity)
    if (quantity === null) {
      setError('Enter a whole quantity greater than zero.')
      return
    }

    setBusyOrderId(order.order_id)
    setError(null)
    try {
      const response = await amendOrder(order.order_id, {
        account: order.account,
        quantity,
        limit_price: parsePositiveNumber(draftEdit.limitPrice),
        take_profit_price: parsePositiveNumber(draftEdit.takeProfitPrice),
        stop_loss_price: parsePositiveNumber(draftEdit.stopLossPrice),
        time_in_force: draftEdit.timeInForce,
      })
      toast.success(response.message)
      setEditingGroupId(null)
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
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">
            Orders
          </h1>
          <AccountSelector
            accounts={accounts}
            activeAccount={selectedAccount ?? undefined}
            onAccountChange={onSelectedAccountChange}
          />
        </div>
        <p className="text-sm text-muted-foreground">
          Active IB orders and current-day terminal history.
        </p>
      </header>

      {error ? <Alert variant="destructive">{error}</Alert> : null}
      {warning ? <Alert variant="muted">{warning}</Alert> : null}

      <OrderSection
        busyOrderId={busyOrderId}
        draftEdit={draftEdit}
        editingGroupId={editingGroupId}
        emptyMessage="No open orders."
        groups={openOrderGroups}
        title="Open"
        onCancel={handleCancel}
        onDraftEditChange={setDraftEdit}
        onEdit={beginEdit}
        onSave={handleSave}
        onStopEdit={() => {
          setEditingGroupId(null)
          setDraftEdit(null)
        }}
      />

      <OrderSection
        busyOrderId={busyOrderId}
        draftEdit={draftEdit}
        editingGroupId={editingGroupId}
        emptyMessage="No current-day order history."
        history
        groups={historyOrderGroups}
        title="History"
        onCancel={handleCancel}
        onDraftEditChange={setDraftEdit}
        onEdit={beginEdit}
        onSave={handleSave}
        onStopEdit={() => {
          setEditingGroupId(null)
          setDraftEdit(null)
        }}
      />
    </main>
  )
}

function OrderSection({
  busyOrderId,
  draftEdit,
  editingGroupId,
  emptyMessage,
  groups,
  history = false,
  title,
  onCancel,
  onDraftEditChange,
  onEdit,
  onSave,
  onStopEdit,
}: {
  busyOrderId: number | null
  draftEdit: DraftEdit | null
  editingGroupId: number | null
  emptyMessage: string
  groups: OrderGroup[]
  history?: boolean
  title: string
  onCancel: (order: OrderRecord) => void
  onDraftEditChange: (draft: DraftEdit) => void
  onEdit: (group: OrderGroup) => void
  onSave: (group: OrderGroup) => void
  onStopEdit: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {groups.length ? (
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
              {groups.map((group) => (
                <OrderRow
                  busyOrderId={busyOrderId}
                  draftEdit={draftEdit}
                  editingGroupId={editingGroupId}
                  history={history}
                  key={group.groupId}
                  group={group}
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
  editingGroupId,
  group,
  history,
  onCancel,
  onDraftEditChange,
  onEdit,
  onSave,
  onStopEdit,
}: {
  busyOrderId: number | null
  draftEdit: DraftEdit | null
  editingGroupId: number | null
  group: OrderGroup
  history: boolean
  onCancel: (order: OrderRecord) => void
  onDraftEditChange: (draft: DraftEdit) => void
  onEdit: (group: OrderGroup) => void
  onSave: (group: OrderGroup) => void
  onStopEdit: () => void
}) {
  const order = group.primary
  const isEditing = editingGroupId === group.groupId && draftEdit !== null
  const isBusy = busyOrderId === order.order_id
  const canEdit = group.readOnlyReason === null
  const displayDetails = order.display_details ?? [`API order ${order.order_id}`]

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{order.preview.summary}</div>
        <div className="max-w-md truncate text-xs text-muted-foreground">
          {displayDetails.join(' | ')}
        </div>
        {order.parent_order_id ? (
          <div className="text-xs text-muted-foreground">
            Child of #{order.parent_order_id}
          </div>
        ) : null}
        {group.children.length ? (
          <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
            <div>{linkedExitSummary(order)}</div>
            {group.children.map((child) => (
              <div key={child.order_id}>Linked order #{child.order_id}</div>
            ))}
          </div>
        ) : null}
      </TableCell>
      <TableCell>
        <div className="capitalize">{order.status.replace('_', ' ')}</div>
        {order.reconciliation_status === 'pending' ? (
          <div className="text-xs text-muted-foreground">Pending IB confirmation</div>
        ) : order.reconciliation_status === 'stale' ? (
          <div className="text-xs text-muted-foreground">
            Not in latest IB open orders
          </div>
        ) : null}
      </TableCell>
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
          <EditableSummary group={group} />
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
                onClick={() => onSave(group)}
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
                  onClick={() => onEdit(group)}
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
        <FieldLabel className="sr-only">Quantity</FieldLabel>
        <Input
          aria-label={`Quantity ${order.order_id}`}
          placeholder="Quantity"
          type="number"
          step="1"
          min="1"
          value={draft.quantity}
          onChange={(event) =>
            onChange({ ...draft, quantity: event.target.value })
          }
        />
      </Field>
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

function EditableSummary({ group }: { group: OrderGroup }) {
  const order = group.primary
  const request = order.preview.request
  if (group.readOnlyReason) {
    return (
      <span className="text-sm text-muted-foreground">
        {group.readOnlyReason}
      </span>
    )
  }

  const values = [
    `Qty ${modeledQuantity(order)}`,
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

function groupOrders(orders: OrderRecord[]): OrderGroup[] {
  const byId = new Map(orders.map((order) => [order.order_id, order]))
  const childIds = new Set(
    orders
      .filter((order) => order.parent_order_id !== null && byId.has(order.parent_order_id))
      .map((order) => order.order_id),
  )

  return orders
    .filter((order) => !childIds.has(order.order_id))
    .map((order) => {
      const children = orders
        .filter((child) => child.parent_order_id === order.order_id)
        .sort((left, right) => left.order_id - right.order_id)
      const records = [order, ...children]
      return {
        groupId: order.parent_order_id ?? order.order_id,
        primary: order,
        children,
        records,
        readOnlyReason: groupReadOnlyReason(order, records),
      }
    })
}

function groupReadOnlyReason(primary: OrderRecord, records: OrderRecord[]) {
  if (primary.parent_order_id !== null) {
    return 'Linked parent order is missing.'
  }
  if (records.some((record) => record.reconciliation_status === 'stale')) {
    return 'Order is not in the latest IB open-order snapshot.'
  }
  const readOnlyRecord = records.find((record) => record.editable === false)
  if (readOnlyRecord) {
    return readOnlyRecord.read_only_reason ?? 'Order is read-only.'
  }
  const request = primary.preview.request
  const needsLinkedOrders =
    request.order_kind === 'option_strategy' &&
    (request.take_profit_price !== undefined ||
      request.stop_loss_price !== undefined) &&
    (request.take_profit_price !== null || request.stop_loss_price !== null)
  if (needsLinkedOrders && records.length === 1) {
    return 'Linked exit orders are incomplete.'
  }
  return null
}

function modeledQuantity(order: OrderRecord) {
  const request = order.preview.request
  if (request.order_kind === 'stock') {
    return request.quantity
  }
  if (request.legs.length === 1) {
    return request.legs[0].quantity
  }
  return request.strategy_quantity ?? 1
}

function linkedExitSummary(order: OrderRecord) {
  const request = order.preview.request
  if (request.order_kind !== 'option_strategy') {
    return 'Linked exits'
  }
  const exits = [
    request.take_profit_price ? `TP ${request.take_profit_price.toFixed(2)}` : null,
    request.stop_loss_price ? `SL ${request.stop_loss_price.toFixed(2)}` : null,
  ].filter(Boolean)
  return exits.length ? `Linked exits: ${exits.join(' | ')}` : 'Linked exits'
}
