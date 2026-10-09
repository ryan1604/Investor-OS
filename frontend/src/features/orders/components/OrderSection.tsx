import { LoaderCircle, Save, XCircle } from 'lucide-react'

import type { OrderRecord, OrderTimeInForce } from '@/api/orders'
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
import { formatQuantity, linkedExitSummary, modeledQuantity, type OrderGroup } from '@/features/orders/lib/orderGroups'

export type DraftEdit = {
  quantity: string
  limitPrice: string
  takeProfitPrice: string
  stopLossPrice: string
  timeInForce: OrderTimeInForce
}

type OrderEditControls = {
  busyOrderId: number | null
  draftEdit: DraftEdit | null
  editingGroupId: number | null
  onCancel: (order: OrderRecord) => void
  onDraftEditChange: (draft: DraftEdit) => void
  onEdit: (group: OrderGroup) => void
  onSave: (group: OrderGroup) => void
  onStopEdit: () => void
}

export function OrderSection({
  controls,
  emptyMessage,
  groups,
  history = false,
  title,
}: {
  controls?: OrderEditControls
  emptyMessage: string
  groups: OrderGroup[]
  history?: boolean
  title: string
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
                  controls={controls}
                  history={history}
                  key={group.groupId}
                  group={group}
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

function OrderRow({ controls, group, history }: {
  controls?: OrderEditControls
  group: OrderGroup
  history: boolean
}) {
  const order = group.primary
  const isEditing = controls?.editingGroupId === group.groupId && controls.draftEdit !== null
  const isBusy = controls?.busyOrderId === order.order_id
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
        {isEditing && controls?.draftEdit ? (
          <OrderEditFields
            draft={controls.draftEdit}
            order={order}
            onChange={controls.onDraftEditChange}
          />
        ) : (
          <EditableSummary group={group} />
        )}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-2">
          {history || !controls ? null : isEditing ? (
            <>
              <Button
                aria-label={`Save order ${order.order_id}`}
                size="sm"
                type="button"
                disabled={isBusy}
                onClick={() => controls.onSave(group)}
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
                onClick={controls.onStopEdit}
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
                  onClick={() => controls.onEdit(group)}
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
                    <AlertDialogAction onClick={() => controls.onCancel(order)}>
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

