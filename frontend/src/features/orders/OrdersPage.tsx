import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { amendOrder, cancelOrder, type OrderRecord } from '@/api/orders'
import { AccountSelector } from '@/components/AccountSelector'
import { Alert } from '@/components/ui/alert'
import { OrderSection, type DraftEdit } from '@/features/orders/components/OrderSection'
import { groupOrders, modeledQuantity, type OrderGroup } from '@/features/orders/lib/orderGroups'
import { orderErrorMessage, parsePositiveInteger, parsePositiveNumber } from '@/features/orders/lib/orderEntryUtils'

type OrdersPageProps = {
  accounts: string[]
  orders: OrderRecord[]
  selectedAccount: string | null
  warning?: string | null
  onSelectedAccountChange: (account: string) => void
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

  function onStopEdit() {
    setEditingGroupId(null)
    setDraftEdit(null)
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
        controls={{
          busyOrderId,
          draftEdit,
          editingGroupId,
          onCancel: handleCancel,
          onDraftEditChange: setDraftEdit,
          onEdit: beginEdit,
          onSave: handleSave,
          onStopEdit,
        }}
        emptyMessage="No open orders."
        groups={openOrderGroups}
        title="Open"
      />

      <OrderSection
        emptyMessage="No current-day order history."
        history
        groups={historyOrderGroups}
        title="History"
      />
    </main>
  )
}
