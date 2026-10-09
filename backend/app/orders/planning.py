from __future__ import annotations

from uuid import uuid4
from typing import TYPE_CHECKING

from ibapi.contract import ComboLeg, Contract
from ibapi.order import Order

from app.ib.contracts import option_right_code, us_equity_contract, us_option_contract
from app.orders.errors import OrderServiceValidationError
from app.orders.ib_contracts import resolve_option_con_id
from app.schemas import (
    OrderAmendmentRequest,
    OptionStrategyOrderRequest,
    OrderRecord,
    StockOrderRequest,
)

if TYPE_CHECKING:
    from app.orders.service import IbOrderApp


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


def modeled_order_quantity(
    request: StockOrderRequest | OptionStrategyOrderRequest,
) -> int:
    if request.order_kind == "stock":
        return request.quantity
    if len(request.legs) == 1:
        return request.legs[0].quantity
    return request.strategy_quantity


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


def build_ib_order(
    request: StockOrderRequest | OptionStrategyOrderRequest,
    app: IbOrderApp | None = None,
) -> tuple[Contract, Order]:
    planned_order = build_ib_order_plan(request, app)[0]
    return planned_order.contract, planned_order.order


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
            right=option_right_code(leg.right),
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
