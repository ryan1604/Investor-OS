from __future__ import annotations

from threading import Event
from typing import TYPE_CHECKING

from ibapi.contract import Contract

from app.ib.contracts import option_right_code, us_option_contract
from app.orders.errors import OrderServiceValidationError

if TYPE_CHECKING:
    from app.orders.service import IbOrderApp

CONTRACT_LOOKUP_TIMEOUT_SECONDS = 8


def request_contract_details(app: IbOrderApp, contract: Contract) -> tuple[bool, list]:
    """Ask IB for one contract's details; return whether it answered in time."""
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    app.reqContractDetails(req_id, contract)
    completed = ready.wait(timeout=CONTRACT_LOOKUP_TIMEOUT_SECONDS)

    with app.lock:
        contract_details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)
    return completed, contract_details


def resolve_contract_by_con_id(
    app: IbOrderApp,
    con_id: int,
    *,
    exchange: str,
    symbol: str,
) -> Contract | None:
    contract = Contract()
    contract.conId = con_id
    contract.secType = "OPT"
    contract.exchange = exchange or "SMART"
    contract.currency = "USD"
    if symbol:
        contract.symbol = symbol
    completed, contract_details = request_contract_details(app, contract)

    if not completed or not contract_details:
        return None
    return contract_details[0].contract


def resolve_option_con_id(app: IbOrderApp | None, leg) -> int:
    if app is None:
        raise OrderServiceValidationError(
            "Option combo leg contract ids are unavailable.",
        )

    completed, contract_details = request_contract_details(
        app,
        us_option_contract(
            leg.ticker,
            expiration=leg.expiration,
            strike=leg.strike,
            right=option_right_code(leg.right),
        ),
    )

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
