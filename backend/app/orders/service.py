from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from threading import Event
from typing import Protocol
from uuid import uuid4

from ibapi.contract import ComboLeg, Contract
from ibapi.execution import ExecutionFilter
from ibapi.order import Order

from app.ib.contracts import us_equity_contract, us_option_contract
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

    def reqOpenOrders(self) -> None:
        ...

    def reqExecutions(self, reqId: int, execFilter: ExecutionFilter) -> None:
        ...

    def reqContractDetails(self, reqId: int, contract: Contract) -> None:
        ...


class OrderService:
    def __init__(
        self,
        app: IbOrderApp | None,
        *,
        subscriber_queue_size: int = 32,
    ) -> None:
        self.app = app
        self.lock = threading.Lock()
        self.orders: dict[int, OrderRecord] = {}
        self.subscribers: set[queue.Queue[OrderStatusUpdate]] = set()
        self.subscriber_queue_size = max(1, subscriber_queue_size)

    def reconcile_from_ib(self) -> None:
        app = self._connected_app()
        app.reqOpenOrders()
        with app.lock:
            req_id = app.next_execution_req_id
            app.next_execution_req_id += 1
        app.reqExecutions(req_id, ExecutionFilter())

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
                f"Order {order_id} was reconciled from IB without editable "
                "contract details and cannot be amended.",
            )

        amended_request = amend_order_request(record.preview.request, request)
        contract, order = amended_ib_order(record, amended_request, app, request)
        order.account = record.account
        order.tif = request.time_in_force or amended_request.time_in_force
        if record.parent_order_id is not None:
            order.parentId = record.parent_order_id

        try:
            app.placeOrder(order_id, contract, order)
        except Exception as error:
            raise OrderServiceValidationError(
                f"Interactive Brokers rejected this order amendment: {error}",
            ) from error

        preview = self.preview(amended_request)
        updated_record = record.model_copy(
            update={
                "preview": preview,
                "updated_at": utc_now(),
            },
        )
        with self.lock:
            self.orders[order_id] = updated_record
        self.broadcast(updated_record)
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
    ) -> OrderRecord:
        with self.lock:
            current = self.orders.get(order_id)
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
                )

            updates = {}
            if account and not current.account:
                updates["account"] = account
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
                    "updated_at": utc_now(),
                }
            )
            self.orders[order_id] = next_record

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
    ) -> OrderRecord:
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
    ) -> OrderRecord:
        now = utc_now()
        reconciled_account = account or "IB_RECONCILED"
        preview = OrderPreviewResponse(
            preview_id=f"ib-{order_id}",
            account=reconciled_account,
            order_kind="stock",
            summary=f"IB order {order_id}",
            time_in_force="DAY",
            estimated_order_type="IB_RECONCILED",
            request=StockOrderRequest(
                account=reconciled_account,
                ticker="IB_RECONCILED",
                action="BUY",
                quantity=1,
            ),
        )
        record = OrderRecord(
            order_id=order_id,
            perm_id=perm_id,
            parent_order_id=parent_order_id,
            account=account or "",
            status=status,
            editable=False,
            filled=filled or 0,
            remaining=remaining,
            avg_fill_price=avg_fill_price,
            rejection_message=rejection_message,
            submitted_at=now,
            updated_at=now,
            preview=preview,
        )
        self.orders[order_id] = record
        return record


def build_ib_order(
    request: StockOrderRequest | OptionStrategyOrderRequest,
    app: IbOrderApp | None = None,
) -> tuple[Contract, Order]:
    planned_order = build_ib_order_plan(request, app)[0]
    return planned_order.contract, planned_order.order


ACTIVE_ORDER_STATUSES = {"submitted", "working", "partially_filled"}


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
                "Stock orders only support limit price and time in force edits.",
            )
        if amendment.limit_price is not None:
            if current.order_type != "LIMIT":
                raise OrderServiceValidationError(
                    "Only stock limit orders can edit limit price.",
                )
            updates["limit_price"] = amendment.limit_price
        return current.model_copy(update=updates)

    if amendment.limit_price is not None:
        updates["limit_price"] = amendment.limit_price
    if amendment.take_profit_price is not None:
        updates["take_profit_price"] = amendment.take_profit_price
    if amendment.stop_loss_price is not None:
        updates["stop_loss_price"] = amendment.stop_loss_price
    return current.model_copy(update=updates)


def amended_ib_order(
    record: OrderRecord,
    request: StockOrderRequest | OptionStrategyOrderRequest,
    app: IbOrderApp | None,
    amendment: OrderAmendmentRequest,
) -> tuple[Contract, Order]:
    if request.order_kind == "stock" or record.parent_order_id is None:
        return build_ib_order(request, app)

    contract, parent_order = option_strategy_parent_order(request, app)
    exit_action = opposite_action(parent_order.action)
    exit_quantity = option_strategy_exit_quantity(request.legs)
    if amendment.stop_loss_price is not None:
        return contract, stop_order(exit_action, exit_quantity, amendment.stop_loss_price)
    if amendment.take_profit_price is not None:
        return contract, limit_order(
            exit_action,
            exit_quantity,
            amendment.take_profit_price,
        )
    return contract, parent_order


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
    order = limit_order(net_action, 1, abs(request.limit_price))
    return contract, order


def option_strategy_exit_orders(
    request: OptionStrategyOrderRequest,
    contract: Contract,
    parent_action: str,
) -> list[PlannedOrder]:
    exit_action = opposite_action(parent_action)
    exit_quantity = option_strategy_exit_quantity(request.legs)
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


def option_strategy_exit_quantity(legs: list[OptionStrategyLegRequest]) -> int:
    if len(legs) == 1:
        return legs[0].quantity
    return 1


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
