from __future__ import annotations

import copy
import queue
import threading
from datetime import datetime, timezone
from threading import Event
from typing import Protocol
from uuid import uuid4

from ibapi.contract import Contract
from ibapi.execution import ExecutionFilter
from ibapi.order import Order

from app.orders.errors import OrderServiceUnavailable, OrderServiceValidationError
from app.orders.planning import (
    amend_order_request,
    amended_ib_orders,
    build_ib_order_plan,
    estimated_order_type,
    order_summary,
    validate_amendment_quantity,
)
from app.orders.reconciliation import (
    ACTIVE_ORDER_STATUSES,
    STALE_OPEN_ORDER_REASON,
    can_amend_raw_open_order,
    completed_filled_quantity,
    completed_order_preview,
    completed_order_read_only_reason,
    execution_filled_quantity,
    execution_record_order_id,
    execution_remaining_quantity,
    is_bound_open_order,
    is_reconciled_preview,
    needs_combo_leg_resolution,
    normalize_completed_status,
    normalize_execution_time,
    normalize_ib_status,
    normalized_execution_action,
    normalized_reconciliation_status,
    partial_ib_order_preview,
    pending_if_active,
    preview_with_account,
    read_only_reason,
    reconciled_execution_preview,
    reconstruct_execution_request,
    reconstruct_open_order_request,
    status_only_preview,
)
from app.orders.store import OrderStore
from app.schemas import (
    OrderAmendmentRequest,
    OrderCancellationRequest,
    OrderPreviewResponse,
    OrderPreviewableRequest,
    OrderRecord,
    OrderStatus,
    OrderStatusUpdate,
    OrderSubmissionResponse,
    TERMINAL_ORDER_STATUSES,
)


class IbOrderApp(Protocol):
    lock: threading.Lock
    next_order_id: int | None
    next_execution_req_id: int
    next_contract_details_req_id: int
    contract_details: dict[int, list]
    contract_details_ready_by_req_id: dict[int, Event]

    def isConnected(self) -> bool:
        ...

    def placeOrder(self, orderId: int, contract: Contract, order: Order) -> None:
        ...

    def cancelOrder(self, orderId: int, manualCancelOrderTime: str = "") -> None:
        ...

    def register_submitted_order(self, order_id: int) -> None:
        ...

    def add_open_order_end_listener(self, listener) -> None:
        ...

    def add_execution_listener(self, listener) -> None:
        ...

    def add_execution_end_listener(self, listener) -> None:
        ...

    def add_completed_order_listener(self, listener) -> None:
        ...

    def add_completed_orders_end_listener(self, listener) -> None:
        ...

    def reqOpenOrders(self) -> None:
        ...

    def reqAutoOpenOrders(self, autoBind: bool) -> None:
        ...

    def reqExecutions(self, reqId: int, execFilter: ExecutionFilter) -> None:
        ...

    def reqCompletedOrders(self, apiOnly: bool) -> None:
        ...

    def reqContractDetails(self, reqId: int, contract: Contract) -> None:
        ...


class OrderService:
    def __init__(
        self,
        app: IbOrderApp | None,
        *,
        store: OrderStore,
        subscriber_queue_size: int = 32,
    ) -> None:
        self.app = app
        self.store = store
        self.lock = threading.Lock()
        loaded_orders = store.list_orders()
        self.orders: dict[int, OrderRecord] = {
            record.order_id: pending_if_active(record) for record in loaded_orders
        }
        if loaded_orders:
            self._persist_orders(list(self.orders.values()))
        self.subscribers: set[queue.Queue[OrderStatusUpdate]] = set()
        self.subscriber_queue_size = max(1, subscriber_queue_size)
        self.reconciliation_order_ids: set[int] | None = None
        self.completed_execution_req_ids: set[int] = set()
        self.completed_orders_received = False
        self.pending_open_order_reconstructions: set[tuple[int, int | None]] = set()
        self.open_order_snapshots: dict[int, tuple[Contract, Order]] = {}

    def reconcile_from_ib(self) -> None:
        app = self._connected_app()
        with self.lock:
            self.reconciliation_order_ids = set()
            pending_records = [
                record.model_copy(update={"reconciliation_status": "pending"})
                for record in self.orders.values()
                if record.status in ACTIVE_ORDER_STATUSES
            ]
            self._save_orders(pending_records)
        app.reqAutoOpenOrders(True)
        app.reqOpenOrders()
        with app.lock:
            req_id = app.next_execution_req_id
            app.next_execution_req_id += 1
        app.reqExecutions(req_id, ExecutionFilter())
        app.reqCompletedOrders(False)
        for record in pending_records:
            self.broadcast(record)

    def preview(self, request: OrderPreviewableRequest) -> OrderPreviewResponse:
        return OrderPreviewResponse(
            preview_id=uuid4().hex,
            account=request.account,
            order_kind=request.order_kind,
            summary=order_summary(request),
            time_in_force=request.time_in_force,
            estimated_order_type=estimated_order_type(request),
            request=request,
        )

    def submit(
        self,
        request: OrderPreviewableRequest,
    ) -> OrderSubmissionResponse:
        app = self._connected_app()
        preview = self.preview(request)
        order_plan = build_ib_order_plan(request, app)
        first_order_id = reserve_order_ids(app, len(order_plan))
        for offset, planned_order in enumerate(order_plan):
            planned_order.order_id = first_order_id + offset
            if planned_order.parent_offset is not None:
                planned_order.order.parentId = first_order_id + planned_order.parent_offset
            planned_order.order.account = request.account
            planned_order.order.tif = request.time_in_force

        now = utc_now()
        records = [
            OrderRecord(
                order_id=planned_order.order_id,
                parent_order_id=(
                    planned_order.order.parentId
                    if getattr(planned_order.order, "parentId", 0)
                    else None
                ),
                account=request.account,
                status="submitted",
                submitted_at=now,
                updated_at=now,
                preview=preview,
            )
            for planned_order in order_plan
        ]

        try:
            for planned_order in order_plan:
                app.register_submitted_order(planned_order.order_id)
                app.placeOrder(
                    planned_order.order_id,
                    planned_order.contract,
                    planned_order.order,
                )
        except Exception as error:
            raise OrderServiceValidationError(
                f"Interactive Brokers rejected this order combination: {error}",
            ) from error

        with self.lock:
            self._save_orders(records)

        for record in records:
            self.broadcast(record)

        record = records[0]
        bracket_message = (
            f" with {len(records) - 1} linked exit order(s)"
            if len(records) > 1
            else ""
        )
        return OrderSubmissionResponse(
            order=record,
            message=(
                f"Submitted order {record.order_id}{bracket_message} "
                "to Interactive Brokers."
            ),
        )

    def cancel(
        self,
        order_id: int,
        request: OrderCancellationRequest,
    ) -> OrderRecord:
        app = self._connected_app()
        with self.lock:
            record = self.orders.get(order_id)

        if record is None:
            raise OrderServiceValidationError(f"Order {order_id} is not tracked.")
        if record.account != request.account:
            raise OrderServiceValidationError(
                "Cancellation account does not match the submitted order.",
            )
        if record.status in {"filled", "cancelled", "rejected"}:
            raise OrderServiceValidationError(
                f"Order {order_id} cannot be cancelled from {record.status} status.",
            )

        app.cancelOrder(order_id, "")

        return self.apply_status(
            order_id,
            status="cancelled",
            remaining=record.remaining,
            filled=record.filled,
        )

    def amend(
        self,
        order_id: int,
        request: OrderAmendmentRequest,
    ) -> OrderRecord:
        app = self._connected_app()
        with self.lock:
            record = self.orders.get(order_id)

        if record is None:
            raise OrderServiceValidationError(f"Order {order_id} is not tracked.")
        if record.account != request.account:
            raise OrderServiceValidationError(
                "Amendment account does not match the submitted order.",
            )
        if record.status not in ACTIVE_ORDER_STATUSES:
            raise OrderServiceValidationError(
                f"Order {order_id} cannot be amended from {record.status} status.",
            )
        if not record.editable:
            raise OrderServiceValidationError(
                record.read_only_reason
                or f"Order {order_id} is read-only and cannot be amended.",
            )
        if record.preview.estimated_order_type == "IB_RECONCILED":
            updated_record = self._amend_reconciled_open_order(record, request, app)
            self.broadcast(updated_record)
            return updated_record

        amended_request = amend_order_request(record.preview.request, request)
        group_records = self._amendment_group(record)
        validate_amendment_quantity(group_records, amended_request)
        planned_orders = amended_ib_orders(group_records, amended_request, app, request)

        try:
            for group_record, contract, order in planned_orders:
                app.placeOrder(group_record.order_id, contract, order)
        except Exception as error:
            raise OrderServiceValidationError(
                f"Interactive Brokers rejected part of this order amendment: {error}",
            ) from error

        preview = self.preview(amended_request)
        updated_records = [
            group_record.model_copy(update={"preview": preview, "updated_at": utc_now()})
            for group_record in group_records
        ]
        updated_record = next(
            group_record
            for group_record in updated_records
            if group_record.order_id == record.order_id
        )
        with self.lock:
            self._save_orders(updated_records)
        for group_record in updated_records:
            self.broadcast(group_record)
        return updated_record

    def apply_status(
        self,
        order_id: int,
        *,
        status: OrderStatus,
        filled: float | None = None,
        remaining: float | None = None,
        avg_fill_price: float | None = None,
        perm_id: int | None = None,
        parent_order_id: int | None = None,
        rejection_message: str | None = None,
        account: str | None = None,
        contract: Contract | None = None,
        order: Order | None = None,
    ) -> OrderRecord:
        with self.lock:
            current = self.orders.get(order_id)
            if current is None and perm_id is not None:
                current = self._order_by_perm_id(perm_id)
                if current is not None:
                    order_id = current.order_id
            if current is None:
                return self._reconciled_record(
                    order_id,
                    status=status,
                    filled=filled,
                    remaining=remaining,
                    avg_fill_price=avg_fill_price,
                    perm_id=perm_id,
                    parent_order_id=parent_order_id,
                    rejection_message=rejection_message,
                    account=account,
                    contract=contract,
                    order=order,
                )

            updates = {}
            if account and current.account != account:
                updates["account"] = account
                updates["preview"] = preview_with_account(current.preview, account)
            if normalized_reconciliation_status(status) == "confirmed":
                updates["reconciliation_status"] = "confirmed"
                if current.read_only_reason == STALE_OPEN_ORDER_REASON:
                    updates["editable"] = True
                    updates["read_only_reason"] = None
            if self.reconciliation_order_ids is not None:
                self.reconciliation_order_ids.add(order_id)
            now = utc_now()
            next_record = current.model_copy(
                update={
                    **updates,
                    "status": status,
                    "filled": filled if filled is not None else current.filled,
                    "remaining": (
                        remaining if remaining is not None else current.remaining
                    ),
                    "avg_fill_price": (
                        avg_fill_price
                        if avg_fill_price is not None
                        else current.avg_fill_price
                    ),
                    "perm_id": perm_id if perm_id is not None else current.perm_id,
                    "parent_order_id": (
                        parent_order_id
                        if parent_order_id is not None
                        else current.parent_order_id
                    ),
                    "rejection_message": rejection_message,
                    "terminal_at": (
                        now
                        if status in TERMINAL_ORDER_STATUSES
                        and current.terminal_at is None
                        else current.terminal_at
                    ),
                    "updated_at": now,
                }
            )
            self._save_order(next_record)

        self.broadcast(next_record)
        return next_record

    def handle_ib_order_status(
        self,
        order_id: int,
        status: str,
        *,
        filled: float | None = None,
        remaining: float | None = None,
        avg_fill_price: float | None = None,
        perm_id: int | None = None,
        parent_order_id: int | None = None,
        rejection_message: str | None = None,
        account: str | None = None,
        contract: Contract | None = None,
        order: Order | None = None,
        order_state=None,
    ) -> OrderRecord:
        if contract is not None and order is not None:
            return self.handle_ib_open_order(
                order_id,
                status,
                contract=contract,
                order=order,
                order_state=order_state,
                filled=filled,
                remaining=remaining,
                perm_id=perm_id,
                parent_order_id=parent_order_id,
                account=account,
            )
        normalized_status = normalize_ib_status(status)
        with self.lock:
            current = self.orders.get(order_id)
        if current is not None and current.status == "cancelled":
            if normalized_status == "rejected":
                normalized_status = "cancelled"
        if normalized_status == "working" and filled and remaining and remaining > 0:
            normalized_status = "partially_filled"
        return self.apply_status(
            order_id,
            status=normalized_status,
            filled=filled,
            remaining=remaining,
            avg_fill_price=avg_fill_price,
            perm_id=perm_id,
            parent_order_id=parent_order_id,
            rejection_message=rejection_message,
            account=account,
        )

    def handle_ib_open_order(
        self,
        order_id: int,
        status: str,
        *,
        contract: Contract,
        order: Order,
        order_state,
        filled: float | None,
        remaining: float | None,
        perm_id: int | None,
        parent_order_id: int | None,
        account: str | None,
    ) -> OrderRecord:
        normalized_status = normalize_ib_status(status)
        reconstructed = reconstruct_open_order_request(contract, order)
        editable = is_bound_open_order(order_id, order) and (
            reconstructed is not None or can_amend_raw_open_order(contract, order)
        )
        callback_account = getattr(order, "account", "") or account
        current = None
        with self.lock:
            self.open_order_snapshots[order_id] = (
                copy.copy(contract),
                copy.copy(order),
            )
            current = self.orders.get(order_id)
            if current is None and perm_id is not None:
                current = self._order_by_perm_id(perm_id)
                if current is not None:
                    current = self._move_order_record(current, order_id)

        if current is None and reconstructed is not None:
            now = utc_now()
            preview = self.preview(reconstructed)
            record = OrderRecord(
                order_id=order_id,
                perm_id=perm_id,
                parent_order_id=parent_order_id,
                account=callback_account or reconstructed.account,
                status=normalized_status,
                reconciliation_status=normalized_reconciliation_status(
                    normalized_status,
                ),
                editable=editable,
                read_only_reason=read_only_reason(order_id, editable, reconstructed),
                filled=filled or 0,
                remaining=remaining,
                submitted_at=now,
                updated_at=now,
                preview=preview,
            )
            with self.lock:
                self.orders[order_id] = record
                if self.reconciliation_order_ids is not None:
                    self.reconciliation_order_ids.add(order_id)
                self._persist_order(record)
            self.broadcast(record)
            return record

        record = self.apply_status(
            order_id,
            status=normalized_status,
            filled=filled,
            remaining=remaining,
            perm_id=perm_id,
            parent_order_id=parent_order_id,
            account=callback_account,
            contract=contract,
            order=order,
        )
        callback_read_only_reason = read_only_reason(order_id, editable, reconstructed)
        if (
            record.editable != editable
            or record.read_only_reason != callback_read_only_reason
        ):
            record = record.model_copy(
                update={
                    "editable": editable,
                    "read_only_reason": callback_read_only_reason,
                    "updated_at": utc_now(),
                },
            )
            self._save_and_broadcast(record)
        if reconstructed is not None and is_reconciled_preview(record):
            preview = self.preview(reconstructed)
            record = record.model_copy(
                update={
                    "account": callback_account or reconstructed.account,
                    "editable": editable,
                    "read_only_reason": read_only_reason(
                        order_id,
                        editable,
                        reconstructed,
                    ),
                    "preview": preview,
                    "updated_at": utc_now(),
                },
            )
            self._save_and_broadcast(record)
        elif reconstructed is None and is_reconciled_preview(record):
            preview = partial_ib_order_preview(
                order_id,
                contract=contract,
                order=order,
                account=callback_account,
            )
            record = record.model_copy(
                update={
                    "account": callback_account or record.account,
                    "preview": preview,
                    "updated_at": utc_now(),
                },
            )
            self._save_and_broadcast(record)
        if reconstructed is None:
            self._schedule_open_order_reconstruction(
                order_id,
                contract=contract,
                order=order,
                perm_id=perm_id,
                account=callback_account,
            )
        return record

    def handle_ib_open_order_end(self) -> None:
        with self.lock:
            seen_order_ids = self.reconciliation_order_ids
            self.reconciliation_order_ids = None
            if seen_order_ids is None:
                return
            now = utc_now()
            stale_records = [
                record.model_copy(
                    update={
                        "status": "stale",
                        "reconciliation_status": "stale",
                        "editable": False,
                        "read_only_reason": STALE_OPEN_ORDER_REASON,
                        "updated_at": now,
                    },
                )
                for record in self.orders.values()
                if record.status in ACTIVE_ORDER_STATUSES
                and record.order_id not in seen_order_ids
            ]
            self._save_orders(stale_records)
        for record in stale_records:
            self.broadcast(record)

    def handle_ib_execution(
        self,
        *,
        req_id: int,
        contract: Contract,
        execution_id: str | None,
        order_id: int,
        perm_id: int | None,
        account: str | None,
        side: str | None,
        shares: float | None,
        price: float | None,
        avg_price: float | None,
        cumulative_quantity: float | None,
        execution_time: str | None,
    ) -> OrderRecord | None:
        if execution_id:
            with self.lock:
                duplicate = self._order_by_execution_id(execution_id)
            if duplicate is not None:
                return duplicate

        action = normalized_execution_action(side)
        executed_at = normalize_execution_time(execution_time) or utc_now()
        with self.lock:
            current = self._order_by_perm_or_order_id(perm_id, order_id)

            if current is None:
                record = self._execution_record(
                    contract=contract,
                    execution_id=execution_id,
                    order_id=order_id,
                    perm_id=perm_id,
                    account=account,
                    action=action,
                    shares=shares,
                    price=price,
                    avg_price=avg_price,
                    cumulative_quantity=cumulative_quantity,
                    executed_at=executed_at,
                )
            else:
                filled = execution_filled_quantity(current, shares, cumulative_quantity)
                remaining = execution_remaining_quantity(current, shares)
                status: OrderStatus = "partially_filled"
                if remaining == 0 or current.status not in ACTIVE_ORDER_STATUSES:
                    status = "filled"
                execution_ids = list(current.execution_ids)
                if execution_id:
                    execution_ids.append(execution_id)
                record = current.model_copy(
                    update={
                        "status": status,
                        "reconciliation_status": "confirmed",
                        "editable": False if status == "filled" else current.editable,
                        "read_only_reason": (
                            None
                            if current.read_only_reason == STALE_OPEN_ORDER_REASON
                            else current.read_only_reason
                        ),
                        "filled": filled,
                        "remaining": remaining,
                        "avg_fill_price": avg_price or price or current.avg_fill_price,
                        "perm_id": perm_id if perm_id is not None else current.perm_id,
                        "account": account or current.account,
                        "execution_id": execution_id or current.execution_id,
                        "execution_ids": execution_ids,
                        "execution_time": executed_at,
                        "execution_side": action or side,
                        "execution_quantity": shares,
                        "execution_price": price,
                        "execution_cumulative_quantity": cumulative_quantity,
                        "updated_at": executed_at,
                    },
                )
                self._save_order(record)

        self.broadcast(record)
        return record

    def handle_ib_execution_end(self, req_id: int) -> None:
        with self.lock:
            self.completed_execution_req_ids.add(req_id)

    def handle_ib_completed_order(
        self,
        *,
        contract: Contract,
        order: Order,
        order_state,
    ) -> OrderRecord | None:
        status = normalize_completed_status(
            completed_order_status(order_state) or "",
        )
        if status is None:
            return None

        order_id = getattr(order, "orderId", 0) or 0
        perm_id = getattr(order, "permId", 0) or None
        account = getattr(order, "account", "") or None
        parent_order_id = getattr(order, "parentId", 0) or None
        completed_at = (
            normalize_execution_time(getattr(order_state, "completedTime", None))
            or utc_now()
        )
        reconstructed = reconstruct_open_order_request(contract, order, self.app)
        with self.lock:
            current = self._order_by_perm_or_order_id(perm_id, order_id)

            if current is None:
                record_order_id = execution_record_order_id(
                    order_id,
                    perm_id,
                    None,
                    set(self.orders),
                )
                preview = (
                    self.preview(reconstructed)
                    if reconstructed is not None
                    else completed_order_preview(record_order_id, contract, order, account)
                )
                record = OrderRecord(
                    order_id=record_order_id,
                    perm_id=perm_id,
                    parent_order_id=parent_order_id,
                    account=account or preview.account,
                    status=status,
                    reconciliation_status="confirmed",
                    editable=False,
                    read_only_reason=completed_order_read_only_reason(reconstructed),
                    filled=completed_filled_quantity(status, order),
                    remaining=0,
                    completed_time=completed_at,
                    completed_status=completed_order_status(order_state),
                    submitted_at=completed_at,
                    updated_at=completed_at,
                    preview=preview,
                )
            else:
                preview = current.preview
                read_only_reason = current.read_only_reason
                if reconstructed is not None and is_reconciled_preview(current):
                    preview = self.preview(reconstructed)
                    read_only_reason = None
                elif current.read_only_reason == STALE_OPEN_ORDER_REASON:
                    read_only_reason = None
                record = current.model_copy(
                    update={
                        "status": status,
                        "reconciliation_status": "confirmed",
                        "editable": False,
                        "read_only_reason": read_only_reason,
                        "filled": (
                            completed_filled_quantity(status, order)
                            if status == "filled"
                            else current.filled
                        ),
                        "remaining": 0,
                        "perm_id": perm_id if perm_id is not None else current.perm_id,
                        "parent_order_id": (
                            parent_order_id
                            if parent_order_id is not None
                            else current.parent_order_id
                        ),
                        "account": account or current.account,
                        "completed_time": completed_at,
                        "completed_status": completed_order_status(order_state),
                        "updated_at": completed_at,
                        "preview": preview,
                    },
                )
            self._save_order(record)

        self.broadcast(record)
        return record

    def handle_ib_completed_orders_end(self) -> None:
        with self.lock:
            self.completed_orders_received = True

    def snapshot(self) -> list[OrderRecord]:
        with self.lock:
            return list(self.orders.values())

    def subscribe(self) -> queue.Queue[OrderStatusUpdate]:
        subscriber: queue.Queue[OrderStatusUpdate] = queue.Queue(
            maxsize=self.subscriber_queue_size,
        )
        with self.lock:
            self.subscribers.add(subscriber)
            orders = list(self.orders.values())
        subscriber.put(OrderStatusUpdate(type="snapshot", orders=orders))
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[OrderStatusUpdate]) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def broadcast(self, order: OrderRecord) -> None:
        update = OrderStatusUpdate(type="update", order=order)
        with self.lock:
            subscribers = list(self.subscribers)

        for subscriber in subscribers:
            put_latest(subscriber, update)

    def _connected_app(self) -> IbOrderApp:
        if self.app is None:
            raise OrderServiceUnavailable("Order service is not connected to IB.")
        if not self.app.isConnected():
            raise OrderServiceUnavailable("Interactive Brokers is not connected.")
        return self.app

    def _reconciled_record(
        self,
        order_id: int,
        *,
        status: OrderStatus,
        filled: float | None,
        remaining: float | None,
        avg_fill_price: float | None,
        perm_id: int | None,
        parent_order_id: int | None,
        rejection_message: str | None,
        account: str | None,
        contract: Contract | None = None,
        order: Order | None = None,
    ) -> OrderRecord:
        now = utc_now()
        reconciled_account = account or "IB_RECONCILED"
        preview = (
            partial_ib_order_preview(
                order_id,
                contract=contract,
                order=order,
                account=reconciled_account,
            )
            if contract is not None or order is not None
            else status_only_preview(
                order_id,
                account=reconciled_account,
                status=status,
                filled=filled,
                remaining=remaining,
                avg_fill_price=avg_fill_price,
            )
        )
        record = OrderRecord(
            order_id=order_id,
            perm_id=perm_id,
            parent_order_id=parent_order_id,
            account=account or "",
            status=status,
            reconciliation_status=normalized_reconciliation_status(status),
            editable=False,
            read_only_reason="Order details were not fully reconstructed from IB.",
            filled=filled or 0,
            remaining=remaining,
            avg_fill_price=avg_fill_price,
            rejection_message=rejection_message,
            terminal_at=now if status in TERMINAL_ORDER_STATUSES else None,
            submitted_at=now,
            updated_at=now,
            preview=preview,
        )
        self._save_order(record)
        return record

    def _order_by_perm_id(self, perm_id: int) -> OrderRecord | None:
        for record in self.orders.values():
            if record.perm_id == perm_id:
                return record
        return None

    def _order_by_perm_or_order_id(
        self, perm_id: int | None, order_id: int,
    ) -> OrderRecord | None:
        current = self._order_by_perm_id(perm_id) if perm_id is not None else None
        if current is None and order_id:
            current = self.orders.get(order_id)
        return current

    def _order_by_execution_id(self, execution_id: str) -> OrderRecord | None:
        for record in self.orders.values():
            if execution_id in record.execution_ids:
                return record
        return None

    def _schedule_open_order_reconstruction(
        self,
        order_id: int,
        *,
        contract: Contract,
        order: Order,
        perm_id: int | None,
        account: str | None,
    ) -> None:
        if self.app is None or not needs_combo_leg_resolution(contract, order):
            return
        key = (order_id, perm_id)
        with self.lock:
            if key in self.pending_open_order_reconstructions:
                return
            self.pending_open_order_reconstructions.add(key)
        thread = threading.Thread(
            target=self._reconstruct_open_order_later,
            args=(key, order_id, contract, order, perm_id, account),
            daemon=True,
        )
        thread.start()

    def _reconstruct_open_order_later(
        self,
        key: tuple[int, int | None],
        order_id: int,
        contract: Contract,
        order: Order,
        perm_id: int | None,
        account: str | None,
    ) -> None:
        try:
            reconstructed = reconstruct_open_order_request(contract, order, self.app)
            if reconstructed is None:
                return
            editable = is_bound_open_order(order_id, order)
            preview = self.preview(reconstructed)
            updated = None
            with self.lock:
                current = self.orders.get(order_id)
                if current is None and perm_id is not None:
                    current = self._order_by_perm_id(perm_id)
                if current is None or current.status not in ACTIVE_ORDER_STATUSES:
                    return
                updated = current.model_copy(
                    update={
                        "account": account or reconstructed.account,
                        "editable": editable,
                        "read_only_reason": read_only_reason(
                            current.order_id,
                            editable,
                            reconstructed,
                        ),
                        "preview": preview,
                        "updated_at": utc_now(),
                    },
                )
                self._save_order(updated)
            self.broadcast(updated)
        finally:
            with self.lock:
                self.pending_open_order_reconstructions.discard(key)

    def _execution_record(
        self,
        *,
        contract: Contract,
        execution_id: str | None,
        order_id: int,
        perm_id: int | None,
        account: str | None,
        action: str | None,
        shares: float | None,
        price: float | None,
        avg_price: float | None,
        cumulative_quantity: float | None,
        executed_at: str,
    ) -> OrderRecord:
        record_order_id = execution_record_order_id(
            order_id,
            perm_id,
            execution_id,
            set(self.orders),
        )
        request = reconstruct_execution_request(
            contract,
            account=account,
            action=action,
            shares=shares,
            price=price,
        )
        preview = reconciled_execution_preview(
            record_order_id,
            contract=contract,
            account=account,
            action=action,
            shares=shares,
            price=price,
            request=request,
        )
        record = OrderRecord(
            order_id=record_order_id,
            perm_id=perm_id,
            account=account or preview.account,
            status="filled",
            reconciliation_status="confirmed",
            editable=False,
            read_only_reason="Execution was reported by IB without editable open-order details.",
            filled=cumulative_quantity or shares or 0,
            remaining=0,
            avg_fill_price=avg_price or price,
            execution_id=execution_id,
            execution_ids=[execution_id] if execution_id else [],
            execution_time=executed_at,
            execution_side=action,
            execution_quantity=shares,
            execution_price=price,
            execution_cumulative_quantity=cumulative_quantity,
            submitted_at=executed_at,
            updated_at=executed_at,
            preview=preview,
        )
        self._save_order(record)
        return record

    def _move_order_record(self, record: OrderRecord, order_id: int) -> OrderRecord:
        if record.order_id == order_id:
            return record
        self.orders.pop(record.order_id, None)
        snapshot = self.open_order_snapshots.pop(record.order_id, None)
        moved = record.model_copy(update={"order_id": order_id, "updated_at": utc_now()})
        self.orders[order_id] = moved
        if snapshot is not None:
            self.open_order_snapshots[order_id] = snapshot
        self.store.delete_order(record.order_id)
        self.store.upsert_order(moved)
        return moved

    def _amend_reconciled_open_order(
        self,
        record: OrderRecord,
        request: OrderAmendmentRequest,
        app: IbOrderApp,
    ) -> OrderRecord:
        snapshot = self.open_order_snapshots.get(record.order_id)
        if snapshot is None:
            raise OrderServiceValidationError(
                "Order details were not fully reconstructed from IB.",
            )
        contract, order = copy.copy(snapshot[0]), copy.copy(snapshot[1])
        if request.take_profit_price is not None or request.stop_loss_price is not None:
            raise OrderServiceValidationError(
                "Reconciled IB orders only support quantity, limit price, and time in force edits.",
            )
        if request.quantity is not None:
            order.totalQuantity = request.quantity
        if request.limit_price is not None:
            if (getattr(order, "orderType", "") or "").upper() != "LMT":
                raise OrderServiceValidationError(
                    "Only limit orders support limit price edits.",
                )
            order.lmtPrice = request.limit_price
        if request.time_in_force is not None:
            order.tif = request.time_in_force
        order.account = record.account

        app.placeOrder(record.order_id, contract, order)
        preview = partial_ib_order_preview(
            record.order_id,
            contract=contract,
            order=order,
            account=record.account,
        )
        updated_record = record.model_copy(
            update={"preview": preview, "updated_at": utc_now()},
        )
        with self.lock:
            self.open_order_snapshots[record.order_id] = (contract, order)
            self._save_order(updated_record)
        return updated_record

    def _amendment_group(self, record: OrderRecord) -> list[OrderRecord]:
        with self.lock:
            if record.parent_order_id is not None:
                return [record]
            children = sorted(
                (
                    child
                    for child in self.orders.values()
                    if child.parent_order_id == record.order_id
                    and child.status in ACTIVE_ORDER_STATUSES
                ),
                key=lambda child: child.order_id,
            )
        return [record, *children]

    def _save_and_broadcast(self, record: OrderRecord) -> None:
        with self.lock:
            self._save_order(record)
        self.broadcast(record)

    def _save_order(self, record: OrderRecord) -> None:
        """Update memory and persistence while the caller holds self.lock."""
        self.orders[record.order_id] = record
        self._persist_order(record)

    def _save_orders(self, records: list[OrderRecord]) -> None:
        """Save a whole batch while the caller holds self.lock."""
        for record in records:
            self.orders[record.order_id] = record
        self._persist_orders(records)

    def _persist_order(self, record: OrderRecord) -> None:
        self.store.upsert_order(record)

    def _persist_orders(self, records: list[OrderRecord]) -> None:
        self.store.upsert_orders(records)


def completed_order_status(order_state) -> str | None:
    return (
        getattr(order_state, "completedStatus", None)
        or getattr(order_state, "status", None)
    )


def reserve_order_ids(app: IbOrderApp, count: int) -> int:
    with app.lock:
        first_order_id = app.next_order_id
        if first_order_id is None or first_order_id <= 0:
            raise OrderServiceUnavailable(
                "Interactive Brokers has not provided the next order id.",
            )
        app.next_order_id = first_order_id + count
    return first_order_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def put_latest(
    subscriber: queue.Queue[OrderStatusUpdate],
    update: OrderStatusUpdate,
) -> None:
    if subscriber.full():
        try:
            subscriber.get_nowait()
        except queue.Empty:
            pass
    subscriber.put_nowait(update)
