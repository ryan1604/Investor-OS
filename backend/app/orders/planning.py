from __future__ import annotations

from uuid import uuid4

from ibapi.contract import Contract
from ibapi.order import Order

from app.schemas import (
    OptionStrategyOrderRequest,
    StockOrderRequest,
)


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


def ib_option_right(right: str) -> str:
    return "C" if right == "CALL" else "P"
