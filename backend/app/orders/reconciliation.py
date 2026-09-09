from __future__ import annotations

import re
import zlib
from datetime import datetime, timezone

from ibapi.contract import Contract
from ibapi.order import Order

from app.schemas import (
    OptionStrategyOrderRequest,
    OrderPreviewResponse,
    OrderRecord,
    OrderStatus,
    StockOrderRequest,
)

ACTIVE_ORDER_STATUSES = {"submitted", "working", "partially_filled"}
STALE_OPEN_ORDER_REASON = "Order is not in the latest IB open-order snapshot."


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
