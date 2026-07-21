from __future__ import annotations

import copy
import queue
import re
import threading
import zlib
from datetime import datetime, timezone
from threading import Event
from typing import Protocol
from uuid import uuid4

from ibapi.contract import ComboLeg, Contract
from ibapi.execution import ExecutionFilter
from ibapi.order import Order

from app.ib.contracts import us_equity_contract, us_option_contract
from app.orders.store import OrderStore
from app.schemas import (
    OrderAmendmentRequest,
    OptionStrategyLegRequest,
    OptionStrategyOrderRequest,
    OrderCancellationRequest,
    OrderPreviewResponse,
    OrderPreviewableRequest,
    OrderRecord,
    OrderStatus,
    OrderStatusUpdate,
    OrderSubmissionResponse,
    StockOrderRequest,
    TERMINAL_ORDER_STATUSES,
)


class OrderServiceUnavailable(RuntimeError):
    pass


class OrderServiceValidationError(ValueError):
    pass


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
        store: OrderStore | None = None,
        subscriber_queue_size: int = 32,
    ) -> None:
        self.app = app
        self.store = store
        self.lock = threading.Lock()
        loaded_orders = store.list_orders() if store else []
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
            for record in pending_records:
                self.orders[record.order_id] = record
            self._persist_orders(pending_records)
        if hasattr(app, "reqAutoOpenOrders"):
            app.reqAutoOpenOrders(True)
        app.reqOpenOrders()
        with app.lock:
            req_id = app.next_execution_req_id
            app.next_execution_req_id += 1
        app.reqExecutions(req_id, ExecutionFilter())
        if hasattr(app, "reqCompletedOrders"):
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
            for record in records:
                self.orders[record.order_id] = record
            self._persist_orders(records)

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
            for group_record in updated_records:
                self.orders[group_record.order_id] = group_record
            self._persist_orders(updated_records)
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
            self.orders[order_id] = next_record
            self._persist_order(next_record)

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
            with self.lock:
                self.orders[order_id] = record
                self._persist_order(record)
            self.broadcast(record)
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
            with self.lock:
                self.orders[order_id] = record
                self._persist_order(record)
            self.broadcast(record)
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
            with self.lock:
                self.orders[order_id] = record
                self._persist_order(record)
            self.broadcast(record)
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
            for record in stale_records:
                self.orders[record.order_id] = record
            self._persist_orders(stale_records)
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
            current = self._order_by_perm_id(perm_id) if perm_id is not None else None
            if current is None and order_id:
                current = self.orders.get(order_id)

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
                self.orders[record.order_id] = record
                self._persist_order(record)

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
            getattr(order_state, "completedStatus", None)
            or getattr(order_state, "status", None)
            or "",
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
            current = self._order_by_perm_id(perm_id) if perm_id is not None else None
            if current is None and order_id:
                current = self.orders.get(order_id)

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
                    completed_status=getattr(order_state, "completedStatus", None)
                    or getattr(order_state, "status", None),
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
                        "completed_status": getattr(order_state, "completedStatus", None)
                        or getattr(order_state, "status", None),
                        "updated_at": completed_at,
                        "preview": preview,
                    },
                )
            self.orders[record.order_id] = record
            self._persist_order(record)

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
        self.orders[order_id] = record
        self._persist_order(record)
        return record

    def _order_by_perm_id(self, perm_id: int) -> OrderRecord | None:
        for record in self.orders.values():
            if record.perm_id == perm_id:
                return record
        return None

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
                self.orders[updated.order_id] = updated
                self._persist_order(updated)
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
        self.orders[record.order_id] = record
        self._persist_order(record)
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
        if self.store:
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
            self.orders[record.order_id] = updated_record
            self._persist_order(updated_record)
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

    def _persist_order(self, record: OrderRecord) -> None:
        if self.store is not None:
            self.store.upsert_order(record)

    def _persist_orders(self, records: list[OrderRecord]) -> None:
        if self.store is not None:
            self.store.upsert_orders(records)


def build_ib_order(
    request: StockOrderRequest | OptionStrategyOrderRequest,
    app: IbOrderApp | None = None,
) -> tuple[Contract, Order]:
    planned_order = build_ib_order_plan(request, app)[0]
    return planned_order.contract, planned_order.order


def reconstruct_open_order_request(
    contract: Contract,
    order: Order,
    app: IbOrderApp | None = None,
) -> StockOrderRequest | OptionStrategyOrderRequest | None:
    account = getattr(order, "account", "") or ""
    action = normalized_action(getattr(order, "action", ""))
    quantity = whole_number(getattr(order, "totalQuantity", None))
    tif = normalized_tif(getattr(order, "tif", "DAY") or "DAY")
    order_type = (getattr(order, "orderType", "") or "").upper()
    sec_type = (getattr(contract, "secType", "") or "").upper()
    symbol = (getattr(contract, "symbol", "") or "").upper()
    if not account or action is None or quantity is None or tif is None or not symbol:
        return None

    if sec_type == "STK" and order_type in {"MKT", "LMT"}:
        request = {
            "account": account,
            "ticker": symbol,
            "action": action,
            "quantity": quantity,
            "order_type": "MARKET" if order_type == "MKT" else "LIMIT",
            "time_in_force": tif,
        }
        if order_type == "LMT":
            limit_price = positive_price(getattr(order, "lmtPrice", None))
            if limit_price is None:
                return None
            request["limit_price"] = limit_price
        return StockOrderRequest.model_validate(request)

    if sec_type == "OPT" and order_type == "LMT":
        limit_price = positive_price(getattr(order, "lmtPrice", None))
        leg = option_leg_from_contract(contract, action, quantity)
        if limit_price is None or leg is None:
            return None
        return OptionStrategyOrderRequest.model_validate(
            {
                "account": account,
                "legs": [leg],
                "limit_price": limit_price if action == "BUY" else -limit_price,
                "time_in_force": tif,
            },
        )

    if sec_type == "BAG" and order_type == "LMT":
        limit_price = combo_limit_price(getattr(order, "lmtPrice", None))
        legs = combo_legs_from_contract(contract, app)
        if limit_price is None or not legs:
            return None
        signed_limit = (
            limit_price if limit_price < 0 or action == "BUY" else -limit_price
        )
        return OptionStrategyOrderRequest.model_validate(
            {
                "account": account,
                "legs": legs,
                "strategy_quantity": quantity,
                "limit_price": signed_limit,
                "time_in_force": tif,
            },
        )

    return None


def is_bound_open_order(order_id: int, order: Order) -> bool:
    return order_id != 0 and getattr(order, "clientId", 0) == 0


def can_amend_raw_open_order(contract: Contract, order: Order) -> bool:
    return (
        (getattr(contract, "secType", "") or "").upper() == "BAG"
        and (getattr(order, "orderType", "") or "").upper() == "LMT"
    )


def needs_combo_leg_resolution(contract: Contract, order: Order) -> bool:
    return (
        (getattr(contract, "secType", "") or "").upper() == "BAG"
        and (getattr(order, "orderType", "") or "").upper() == "LMT"
        and bool(getattr(contract, "comboLegs", None))
    )


def preview_with_account(
    preview: OrderPreviewResponse,
    account: str,
) -> OrderPreviewResponse:
    return preview.model_copy(
        update={
            "account": account,
            "request": preview.request.model_copy(update={"account": account}),
        },
    )


def read_only_reason(
    order_id: int,
    editable: bool,
    reconstructed: StockOrderRequest | OptionStrategyOrderRequest | None,
) -> str | None:
    if editable:
        return None
    if reconstructed is None:
        return "Order details were not fully reconstructed from IB."
    return f"Order {order_id} is visible but not bound for modification."


def normalized_action(action: str) -> str | None:
    normalized = action.upper()
    return normalized if normalized in {"BUY", "SELL"} else None


def normalized_tif(tif: str) -> str | None:
    normalized = tif.upper()
    return normalized if normalized in {"DAY", "GTC"} else None


def whole_number(value) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or not number.is_integer():
        return None
    return int(number)


def positive_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def combo_limit_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price != 0 and abs(price) < 1e100 else None


def option_leg_from_contract(
    contract: Contract,
    action: str,
    quantity: int,
) -> dict | None:
    right = normalized_option_right(getattr(contract, "right", ""))
    expiration = getattr(contract, "lastTradeDateOrContractMonth", "") or ""
    strike = positive_price(getattr(contract, "strike", None))
    symbol = (getattr(contract, "symbol", "") or "").upper()
    if not symbol or not expiration or right is None or strike is None:
        return None
    return {
        "con_id": getattr(contract, "conId", 0) or None,
        "ticker": symbol,
        "expiration": expiration,
        "right": right,
        "strike": strike,
        "action": action,
        "quantity": quantity,
    }


def combo_legs_from_contract(
    contract: Contract,
    app: IbOrderApp | None = None,
) -> list[dict] | None:
    legs = []
    symbol = (getattr(contract, "symbol", "") or "").upper()
    descriptions = combo_leg_descriptions(contract)
    for index, combo_leg in enumerate(getattr(contract, "comboLegs", None) or []):
        action = normalized_action(getattr(combo_leg, "action", ""))
        ratio = whole_number(getattr(combo_leg, "ratio", None))
        leg_contract = combo_leg_contract(contract, combo_leg, app)
        details = option_leg_details(
            leg_contract,
            fallback_symbol=symbol,
            fallback_description=(
                descriptions[index] if index < len(descriptions) else None
            ),
        )
        if (
            action is None
            or ratio is None
            or details is None
        ):
            return None
        legs.append(
            {
                "con_id": getattr(combo_leg, "conId", 0) or None,
                "ticker": details["symbol"],
                "expiration": details["expiration"],
                "right": details["right"],
                "strike": details["strike"],
                "action": action,
                "quantity": ratio,
            },
        )
    return legs or None


def combo_leg_contract(
    combo_contract: Contract,
    combo_leg: ComboLeg,
    app: IbOrderApp | None,
) -> Contract | ComboLeg:
    has_details = (
        normalized_option_right(getattr(combo_leg, "right", "")) is not None
        and bool(
            getattr(combo_leg, "expiration", "")
            or getattr(combo_leg, "lastTradeDateOrContractMonth", "")
        )
        and positive_price(getattr(combo_leg, "strike", None)) is not None
        and bool(getattr(combo_leg, "symbol", "") or getattr(combo_contract, "symbol", ""))
    )
    con_id = getattr(combo_leg, "conId", 0) or 0
    if has_details or app is None or not con_id:
        return combo_leg
    return resolve_contract_by_con_id(
        app,
        con_id,
        exchange=getattr(combo_leg, "exchange", "") or "",
        symbol=(getattr(combo_contract, "symbol", "") or "").upper(),
    ) or combo_leg


def option_leg_details(
    contract,
    *,
    fallback_symbol: str,
    fallback_description: str | None,
) -> dict | None:
    parsed = parse_option_local_symbol(getattr(contract, "localSymbol", ""))
    if parsed is None and fallback_description:
        parsed = parse_option_local_symbol(fallback_description)
    right = normalized_option_right(getattr(contract, "right", "")) or (
        parsed["right"] if parsed else None
    )
    expiration = (
        getattr(contract, "expiration", "")
        or getattr(contract, "lastTradeDateOrContractMonth", "")
        or (parsed["expiration"] if parsed else "")
    )
    strike = positive_price(getattr(contract, "strike", None)) or (
        parsed["strike"] if parsed else None
    )
    symbol = (
        getattr(contract, "symbol", "")
        or (parsed["symbol"] if parsed else "")
        or fallback_symbol
    ).upper()
    if not symbol or not expiration or right is None or strike is None:
        return None
    return {
        "symbol": symbol,
        "expiration": expiration,
        "right": right,
        "strike": strike,
    }


def combo_leg_descriptions(contract: Contract) -> list[str]:
    description = getattr(contract, "comboLegsDescrip", "") or ""
    return [part.strip() for part in description.split(",") if part.strip()]


def parse_option_local_symbol(value: str) -> dict | None:
    match = re.search(
        r"(?P<symbol>[A-Z0-9]+)\s+(?P<date>\d{6})(?P<right>[CP])(?P<strike>\d{8})",
        value.upper(),
    )
    if match is None:
        return None
    return {
        "symbol": match.group("symbol"),
        "expiration": f"20{match.group('date')}",
        "right": "CALL" if match.group("right") == "C" else "PUT",
        "strike": int(match.group("strike")) / 1000,
    }


def resolve_contract_by_con_id(
    app: IbOrderApp,
    con_id: int,
    *,
    exchange: str,
    symbol: str,
) -> Contract | None:
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    contract = Contract()
    contract.conId = con_id
    contract.secType = "OPT"
    contract.exchange = exchange or "SMART"
    contract.currency = "USD"
    if symbol:
        contract.symbol = symbol
    app.reqContractDetails(req_id, contract)
    completed = ready.wait(timeout=8)

    with app.lock:
        contract_details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)

    if not completed or not contract_details:
        return None
    return contract_details[0].contract


def normalized_option_right(right: str) -> str | None:
    normalized = right.upper()
    if normalized in {"C", "CALL"}:
        return "CALL"
    if normalized in {"P", "PUT"}:
        return "PUT"
    return None


def normalized_execution_action(side: str | None) -> str | None:
    normalized = (side or "").upper()
    if normalized in {"BOT", "BUY"}:
        return "BUY"
    if normalized in {"SLD", "SELL"}:
        return "SELL"
    return None


def normalize_execution_time(value: str | None) -> str | None:
    if not value:
        return None
    normalized = " ".join(value.strip().split())
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    parts = normalized.split()
    if len(parts) >= 2:
        for candidate in (f"{parts[0]} {parts[1]}", f"{parts[0]}T{parts[1]}"):
            for date_format in ("%Y%m%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return (
                        datetime.strptime(candidate, date_format)
                        .replace(tzinfo=timezone.utc)
                        .isoformat()
                    )
                except ValueError:
                    continue
    return None


def execution_filled_quantity(
    record: OrderRecord,
    shares: float | None,
    cumulative_quantity: float | None,
) -> float:
    if cumulative_quantity is not None:
        return cumulative_quantity
    if shares is not None:
        return record.filled + shares
    return record.filled


def execution_remaining_quantity(
    record: OrderRecord,
    shares: float | None,
) -> float:
    if record.remaining is None:
        return 0
    if shares is None:
        return record.remaining
    return max(record.remaining - shares, 0)


def execution_record_order_id(
    order_id: int,
    perm_id: int | None,
    execution_id: str | None,
    existing_order_ids: set[int],
) -> int:
    if order_id:
        return order_id
    if perm_id:
        candidate = -abs(perm_id)
    elif execution_id:
        candidate = -(zlib.crc32(execution_id.encode("utf-8")) or 1)
    else:
        candidate = -1
    while candidate in existing_order_ids:
        candidate -= 1
    return candidate


def reconstruct_execution_request(
    contract: Contract,
    *,
    account: str | None,
    action: str | None,
    shares: float | None,
    price: float | None,
) -> StockOrderRequest | OptionStrategyOrderRequest | None:
    if not account or action is None:
        return None
    quantity = whole_number(shares)
    if quantity is None:
        return None
    sec_type = (getattr(contract, "secType", "") or "").upper()
    symbol = (getattr(contract, "symbol", "") or "").upper()
    if not symbol:
        return None
    if sec_type == "STK":
        request = {
            "account": account,
            "ticker": symbol,
            "action": action,
            "quantity": quantity,
            "order_type": "MARKET",
        }
        if price is not None and price > 0:
            request["order_type"] = "LIMIT"
            request["limit_price"] = price
        return StockOrderRequest.model_validate(request)
    if sec_type == "OPT" and price is not None and price > 0:
        leg = option_leg_from_contract(contract, action, quantity)
        if leg is None:
            return None
        return OptionStrategyOrderRequest.model_validate(
            {
                "account": account,
                "legs": [leg],
                "limit_price": price if action == "BUY" else -price,
            },
        )
    return None


def status_only_preview(
    order_id: int,
    *,
    account: str,
    status: OrderStatus,
    filled: float | None,
    remaining: float | None,
    avg_fill_price: float | None,
) -> OrderPreviewResponse:
    quantities = []
    if filled is not None:
        quantities.append(f"filled {format_ib_number(filled)}")
    if remaining is not None:
        quantities.append(f"remaining {format_ib_number(remaining)}")
    if avg_fill_price is not None:
        quantities.append(f"avg {format_ib_number(avg_fill_price)}")
    summary = f"IB status-only {status.replace('_', ' ')} order"
    if quantities:
        summary = f"{summary}: {', '.join(quantities)}"
    return OrderPreviewResponse(
        preview_id=f"ib-{order_id}",
        account=account,
        order_kind="stock",
        summary=summary,
        time_in_force="DAY",
        estimated_order_type="IB_RECONCILED",
        request=StockOrderRequest(
            account=account,
            ticker="IB_RECONCILED",
            action="BUY",
            quantity=1,
        ),
    )


def partial_ib_order_preview(
    order_id: int,
    *,
    contract: Contract | None,
    order: Order | None,
    account: str | None,
) -> OrderPreviewResponse:
    reconciled_account = account or getattr(order, "account", None) or "IB_RECONCILED"
    symbol = contract_symbol(contract)
    action = normalized_action(getattr(order, "action", "")) or text_attr(order, "action")
    quantity = positive_quantity(getattr(order, "totalQuantity", None))
    order_type = text_attr(order, "orderType")
    tif = normalized_tif(getattr(order, "tif", "")) or text_attr(order, "tif") or "DAY"
    parts = [
        action,
        format_ib_number(quantity) if quantity is not None else None,
        contract_summary(contract),
        ib_order_type_label(order_type),
        price_label("limit", getattr(order, "lmtPrice", None)),
        price_label("stop", getattr(order, "auxPrice", None)),
        tif,
    ]
    summary = " ".join(part for part in parts if part)
    request_payload = {
        "account": reconciled_account,
        "ticker": symbol or "IB_RECONCILED",
        "action": action if action in {"BUY", "SELL"} else "BUY",
        "quantity": whole_number(quantity) or 1,
        "time_in_force": tif if tif in {"DAY", "GTC"} else "DAY",
    }
    if order_type == "LMT":
        limit_price = positive_price(getattr(order, "lmtPrice", None))
        if limit_price is not None:
            request_payload["order_type"] = "LIMIT"
            request_payload["limit_price"] = limit_price
    request = StockOrderRequest.model_validate(request_payload)
    return OrderPreviewResponse(
        preview_id=f"ib-{order_id}",
        account=reconciled_account,
        order_kind="stock",
        summary=summary or "IB order with incomplete details",
        time_in_force=tif if tif in {"DAY", "GTC"} else "DAY",
        estimated_order_type="IB_RECONCILED",
        request=request,
    )


def contract_symbol(contract: Contract | None) -> str:
    if contract is None:
        return ""
    return (
        getattr(contract, "symbol", None)
        or getattr(contract, "localSymbol", None)
        or ""
    ).upper()


def contract_summary(contract: Contract | None) -> str | None:
    if contract is None:
        return None
    symbol = contract_symbol(contract)
    sec_type = text_attr(contract, "secType")
    if not symbol and not sec_type:
        return None
    if sec_type == "OPT":
        right = normalized_option_right(getattr(contract, "right", "")) or text_attr(
            contract,
            "right",
        )
        parts = [
            symbol,
            sec_type,
            text_attr(contract, "lastTradeDateOrContractMonth"),
            price_value(getattr(contract, "strike", None)),
            right,
        ]
        return " ".join(part for part in parts if part)
    return " ".join(part for part in [symbol, sec_type] if part)


def text_attr(source, name: str) -> str:
    value = getattr(source, name, "") if source is not None else ""
    return str(value).strip().upper() if value else ""


def ib_order_type_label(order_type: str) -> str | None:
    return {"MKT": "MARKET", "LMT": "LIMIT", "STP": "STOP"}.get(
        order_type,
        order_type or None,
    )


def price_label(label: str, value) -> str | None:
    price = price_value(value)
    return f"{label} {price}" if price is not None else None


def price_value(value) -> str | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return format_ib_number(price) if 0 < price < 1e100 else None


def positive_quantity(value) -> float | None:
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return None
    return quantity if quantity > 0 else None


def format_ib_number(value: float) -> str:
    return f"{value:g}"


def reconciled_execution_preview(
    order_id: int,
    *,
    contract: Contract,
    account: str | None,
    action: str | None,
    shares: float | None,
    price: float | None,
    request: StockOrderRequest | OptionStrategyOrderRequest | None = None,
) -> OrderPreviewResponse:
    reconciled_account = account or "IB_RECONCILED"
    symbol = (getattr(contract, "symbol", "") or "IB_RECONCILED").upper()
    quantity = whole_number(shares) or 1
    side = action or "BUY"
    price_summary = f" @ {price:g}" if price is not None else ""
    preview_request = request or StockOrderRequest(
        account=reconciled_account,
        ticker=symbol,
        action=side if side in {"BUY", "SELL"} else "BUY",
        quantity=quantity,
    )
    return OrderPreviewResponse(
        preview_id=f"ib-execution-{order_id}",
        account=reconciled_account,
        order_kind=preview_request.order_kind,
        summary=f"{side} {shares or quantity:g} {contract_summary(contract) or symbol}{price_summary}",
        time_in_force=preview_request.time_in_force,
        estimated_order_type="IB_EXECUTION",
        request=preview_request,
    )


def normalize_completed_status(status: str) -> OrderStatus | None:
    normalized = status.lower().replace(" ", "")
    if normalized in {"filled", "apifilled"}:
        return "filled"
    if normalized in {"cancelled", "canceled", "apicancelled", "apicanceled"}:
        return "cancelled"
    if normalized in {"inactive", "rejected"}:
        return "rejected"
    return None


def completed_filled_quantity(status: OrderStatus, order: Order) -> float:
    if status != "filled":
        return 0
    return float(getattr(order, "totalQuantity", 0) or 0)


def completed_order_read_only_reason(
    reconstructed: StockOrderRequest | OptionStrategyOrderRequest | None,
) -> str | None:
    if reconstructed is not None:
        return None
    return "Completed order details were not fully reconstructed from IB."


def is_reconciled_preview(record: OrderRecord) -> bool:
    return record.preview.estimated_order_type == "IB_RECONCILED"


def completed_order_preview(
    order_id: int,
    contract: Contract,
    order: Order,
    account: str | None,
) -> OrderPreviewResponse:
    reconciled_account = account or "IB_RECONCILED"
    symbol = (getattr(contract, "symbol", "") or "IB_RECONCILED").upper()
    action = normalized_action(getattr(order, "action", "")) or "BUY"
    quantity = whole_number(getattr(order, "totalQuantity", None)) or 1
    order_type = ib_order_type_label(text_attr(order, "orderType"))
    tif = normalized_tif(getattr(order, "tif", "")) or text_attr(order, "tif") or "DAY"
    request = StockOrderRequest(
        account=reconciled_account,
        ticker=symbol,
        action=action,
        quantity=quantity,
    )
    summary = " ".join(
        part
        for part in [
            action,
            f"{quantity:g}",
            contract_summary(contract) or symbol,
            order_type,
            price_label("limit", getattr(order, "lmtPrice", None)),
            price_label("stop", getattr(order, "auxPrice", None)),
            tif,
        ]
        if part
    )
    return OrderPreviewResponse(
        preview_id=f"ib-completed-{order_id}",
        account=reconciled_account,
        order_kind="stock",
        summary=summary,
        time_in_force=tif if tif in {"DAY", "GTC"} else "DAY",
        estimated_order_type="IB_COMPLETED",
        request=request,
    )


ACTIVE_ORDER_STATUSES = {"submitted", "working", "partially_filled"}
STALE_OPEN_ORDER_REASON = "Order is not in the latest IB open-order snapshot."


def reserve_order_ids(app: IbOrderApp, count: int) -> int:
    with app.lock:
        first_order_id = app.next_order_id
        if first_order_id is None or first_order_id <= 0:
            raise OrderServiceUnavailable(
                "Interactive Brokers has not provided the next order id.",
            )
        app.next_order_id = first_order_id + count
    return first_order_id


def amend_order_request(
    current: StockOrderRequest | OptionStrategyOrderRequest,
    amendment: OrderAmendmentRequest,
) -> StockOrderRequest | OptionStrategyOrderRequest:
    updates = {}
    if amendment.time_in_force is not None:
        updates["time_in_force"] = amendment.time_in_force

    if current.order_kind == "stock":
        if amendment.take_profit_price is not None or amendment.stop_loss_price is not None:
            raise OrderServiceValidationError(
                "Stock orders only support quantity, limit price, and time in force edits.",
            )
        if amendment.quantity is not None:
            updates["quantity"] = amendment.quantity
        if amendment.limit_price is not None:
            if current.order_type != "LIMIT":
                raise OrderServiceValidationError(
                    "Only stock limit orders can edit limit price.",
                )
            updates["limit_price"] = amendment.limit_price
        return current.model_copy(update=updates)

    if amendment.limit_price is not None:
        updates["limit_price"] = amendment.limit_price
    if amendment.quantity is not None:
        if len(current.legs) == 1:
            updates["legs"] = [
                current.legs[0].model_copy(update={"quantity": amendment.quantity}),
            ]
        else:
            updates["strategy_quantity"] = amendment.quantity
    if amendment.take_profit_price is not None:
        updates["take_profit_price"] = amendment.take_profit_price
    if amendment.stop_loss_price is not None:
        updates["stop_loss_price"] = amendment.stop_loss_price
    return current.model_copy(update=updates)


def amended_ib_orders(
    records: list[OrderRecord],
    request: StockOrderRequest | OptionStrategyOrderRequest,
    app: IbOrderApp | None,
    amendment: OrderAmendmentRequest,
) -> list[tuple[OrderRecord, Contract, Order]]:
    if len(records) > 1:
        plan = build_ib_order_plan(request, app)
        if len(plan) != len(records):
            raise OrderServiceValidationError(
                "Linked order group is incomplete and cannot be amended safely.",
            )
        parent_id = records[0].order_id
        planned_orders = []
        for record, planned_order in zip(records, plan, strict=True):
            planned_order.order.account = record.account
            planned_order.order.tif = amendment.time_in_force or request.time_in_force
            if record.parent_order_id is not None:
                planned_order.order.parentId = parent_id
            planned_orders.append((record, planned_order.contract, planned_order.order))
        return planned_orders

    record = records[0]
    if request.order_kind == "stock" or record.parent_order_id is None:
        contract, order = build_ib_order(request, app)
        order.account = record.account
        order.tif = amendment.time_in_force or request.time_in_force
        return [(record, contract, order)]

    contract, parent_order = option_strategy_parent_order(request, app)
    exit_action = opposite_action(parent_order.action)
    exit_quantity = option_strategy_exit_quantity(request)
    if amendment.stop_loss_price is not None:
        order = stop_order(exit_action, exit_quantity, amendment.stop_loss_price)
        order.account = record.account
        order.tif = amendment.time_in_force or request.time_in_force
        order.parentId = record.parent_order_id
        return [(record, contract, order)]
    if amendment.take_profit_price is not None:
        order = limit_order(
            exit_action,
            exit_quantity,
            amendment.take_profit_price,
        )
        order.account = record.account
        order.tif = amendment.time_in_force or request.time_in_force
        order.parentId = record.parent_order_id
        return [(record, contract, order)]
    parent_order.account = record.account
    parent_order.tif = amendment.time_in_force or request.time_in_force
    parent_order.parentId = record.parent_order_id
    return [(record, contract, parent_order)]


def validate_amendment_quantity(
    records: list[OrderRecord],
    request: StockOrderRequest | OptionStrategyOrderRequest,
) -> None:
    quantity = modeled_order_quantity(request)
    min_filled = max((record.filled for record in records), default=0)
    if quantity < min_filled:
        raise OrderServiceValidationError(
            "Quantity cannot be reduced below the already-filled quantity.",
        )


def modeled_order_quantity(
    request: StockOrderRequest | OptionStrategyOrderRequest,
) -> int:
    if request.order_kind == "stock":
        return request.quantity
    if len(request.legs) == 1:
        return request.legs[0].quantity
    return request.strategy_quantity


class PlannedOrder:
    def __init__(
        self,
        contract: Contract,
        order: Order,
        *,
        parent_offset: int | None = None,
    ) -> None:
        self.contract = contract
        self.order = order
        self.parent_offset = parent_offset
        self.order_id = 0


def build_ib_order_plan(
    request: StockOrderRequest | OptionStrategyOrderRequest,
    app: IbOrderApp | None = None,
) -> list[PlannedOrder]:
    if request.order_kind == "stock":
        return [PlannedOrder(us_equity_contract(request.ticker), stock_order(request))]

    contract, parent_order = option_strategy_parent_order(request, app)
    exit_orders = option_strategy_exit_orders(request, contract, parent_order.action)
    if exit_orders:
        parent_order.transmit = False
        for exit_order in exit_orders[:-1]:
            exit_order.order.transmit = False
        exit_orders[-1].order.transmit = True
        return [PlannedOrder(contract, parent_order), *exit_orders]

    return [PlannedOrder(contract, parent_order)]


def option_strategy_parent_order(
    request: OptionStrategyOrderRequest,
    app: IbOrderApp | None = None,
) -> tuple[Contract, Order]:
    if len(request.legs) == 1:
        leg = request.legs[0]
        contract = us_option_contract(
            leg.ticker,
            expiration=leg.expiration,
            strike=leg.strike,
            right=ib_option_right(leg.right),
        )
        if leg.con_id:
            contract.conId = leg.con_id
        order = limit_order(leg.action, leg.quantity, abs(request.limit_price))
        return contract, order

    contract = Contract()
    first_leg = request.legs[0]
    contract.symbol = first_leg.ticker
    contract.secType = "BAG"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.comboLegs = []

    for leg in request.legs:
        combo_leg = ComboLeg()
        combo_leg.conId = leg.con_id or resolve_option_con_id(app, leg)
        combo_leg.ratio = leg.quantity
        combo_leg.action = leg.action
        combo_leg.exchange = "SMART"
        contract.comboLegs.append(combo_leg)

    net_action = "BUY" if request.limit_price >= 0 else "SELL"
    order = limit_order(net_action, request.strategy_quantity, abs(request.limit_price))
    return contract, order


def option_strategy_exit_orders(
    request: OptionStrategyOrderRequest,
    contract: Contract,
    parent_action: str,
) -> list[PlannedOrder]:
    exit_action = opposite_action(parent_action)
    exit_quantity = option_strategy_exit_quantity(request)
    exits: list[PlannedOrder] = []

    if request.take_profit_price is not None:
        exits.append(
            PlannedOrder(
                contract,
                limit_order(exit_action, exit_quantity, request.take_profit_price),
                parent_offset=0,
            ),
        )
    if request.stop_loss_price is not None:
        exits.append(
            PlannedOrder(
                contract,
                stop_order(exit_action, exit_quantity, request.stop_loss_price),
                parent_offset=0,
            ),
        )

    if len(exits) == 2:
        oca_group = f"option-bracket-{uuid4().hex}"
        for exit_order in exits:
            exit_order.order.ocaGroup = oca_group
            exit_order.order.ocaType = 1

    return exits


def option_strategy_exit_quantity(request: OptionStrategyOrderRequest) -> int:
    if len(request.legs) == 1:
        return request.legs[0].quantity
    return request.strategy_quantity


def resolve_option_con_id(app: IbOrderApp | None, leg) -> int:
    if app is None:
        raise OrderServiceValidationError(
            "Option combo leg contract ids are unavailable.",
        )

    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    app.reqContractDetails(
        req_id,
        us_option_contract(
            leg.ticker,
            expiration=leg.expiration,
            strike=leg.strike,
            right=ib_option_right(leg.right),
        ),
    )
    completed = ready.wait(timeout=8)

    with app.lock:
        contract_details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)

    if not completed:
        raise OrderServiceValidationError(
            f"Option contract lookup timed out for {leg.ticker} {leg.expiration} "
            f"{leg.strike:g} {leg.right}.",
        )
    if not contract_details:
        raise OrderServiceValidationError(
            f"Option contract is unavailable for {leg.ticker} {leg.expiration} "
            f"{leg.strike:g} {leg.right}.",
        )

    con_id = getattr(contract_details[0].contract, "conId", 0)
    if not con_id:
        raise OrderServiceValidationError(
            f"Option contract id is unavailable for {leg.ticker} {leg.expiration} "
            f"{leg.strike:g} {leg.right}.",
        )
    return con_id


def ib_order() -> Order:
    order = Order()
    order.eTradeOnly = False
    order.firmQuoteOnly = False
    return order


def stock_order(request: StockOrderRequest) -> Order:
    order = ib_order()
    order.action = request.action
    order.orderType = "MKT" if request.order_type == "MARKET" else "LMT"
    order.totalQuantity = request.quantity
    if request.order_type == "LIMIT":
        order.lmtPrice = request.limit_price
    return order


def limit_order(action: str, quantity: float, limit_price: float) -> Order:
    order = ib_order()
    order.action = action
    order.orderType = "LMT"
    order.totalQuantity = quantity
    order.lmtPrice = limit_price
    return order


def stop_order(action: str, quantity: float, stop_price: float) -> Order:
    order = ib_order()
    order.action = action
    order.orderType = "STP"
    order.totalQuantity = quantity
    order.auxPrice = stop_price
    return order


def opposite_action(action: str) -> str:
    return "SELL" if action == "BUY" else "BUY"


def order_summary(request: StockOrderRequest | OptionStrategyOrderRequest) -> str:
    if request.order_kind == "stock":
        return f"{request.action} {request.quantity:g} share(s) {request.ticker}"

    legs = ", ".join(
        f"{leg.action} {leg.quantity} {leg.ticker} {leg.expiration} "
        f"{leg.strike:g} {leg.right}"
        for leg in request.legs
    )
    exits = []
    if request.take_profit_price is not None:
        exits.append(f"take profit {request.take_profit_price:g}")
    if request.stop_loss_price is not None:
        exits.append(f"stop loss {request.stop_loss_price:g}")
    exit_summary = f" with {', '.join(exits)}" if exits else ""
    return f"{legs} @ {request.limit_price:g}{exit_summary}"


def estimated_order_type(
    request: StockOrderRequest | OptionStrategyOrderRequest,
) -> str:
    if request.order_kind == "stock":
        return request.order_type
    if request.take_profit_price is not None or request.stop_loss_price is not None:
        return "LIMIT + BRACKET"
    return "LIMIT"


def ib_option_right(right: str) -> str:
    return "C" if right == "CALL" else "P"


def normalize_ib_status(status: str) -> OrderStatus:
    normalized_status = status.lower()
    if normalized_status in {"presubmitted", "submitted", "pendingsubmit"}:
        return "working"
    if normalized_status in {"filled"}:
        return "filled"
    if normalized_status in {"cancelled", "apicancelled", "pendingcancel"}:
        return "cancelled"
    if normalized_status in {"inactive"}:
        return "rejected"
    return "submitted"


def normalized_reconciliation_status(status: OrderStatus) -> str:
    return "confirmed" if status not in {"submitted"} else "pending"


def pending_if_active(record: OrderRecord) -> OrderRecord:
    if record.status not in ACTIVE_ORDER_STATUSES:
        return record
    return record.model_copy(update={"reconciliation_status": "pending"})


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
