import threading

from app.ib.pacing import OutstandingRequestLimiter
from app.ib.contracts import us_option_contract
from tests.conftest import FakeIbAppBase


class FakeOptionChainIbApp(FakeIbAppBase):
    def __init__(self, contract_strikes: list[float] | None = None) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.next_contract_details_req_id = 70_000
        self.next_option_market_req_id = 90_000
        self.contract_strikes = contract_strikes or [95, 100]
        self.contract_details = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.option_market_req_to_key = {}
        self.option_market_data = {}
        self.option_market_ready_by_req_id: dict[int, threading.Event] = {}
        self.contract_detail_requests = []
        self.market_data_requests = []
        self.cancelled_market_data = []
        self.ib_calls_inside_lock: list[str] = []

    def isConnected(self) -> bool:
        return True

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": option_contract})()
            for right in requested_rights(contract)
            for index, strike in enumerate(self.contract_strikes)
            for option_contract in [
                fake_option_contract(
                    contract,
                    strike,
                    con_id=req_id + index + int(strike * 100),
                    right=right,
                )
            ]
        ]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqMktData(
        self,
        req_id,
        contract,
        generic_tick_list,
        snapshot,
        regulatory_snapshot,
        mkt_data_options,
    ) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("reqMktData")
        self.market_data_requests.append(
            (
                req_id,
                contract,
                generic_tick_list,
                snapshot,
                regulatory_snapshot,
                mkt_data_options,
            )
        )
        self.option_market_data[req_id] = {
            "bid": 1,
            "ask": 1.4,
            "last": 1.5,
            "close": 1.25,
            "delta": 0.5,
            "gamma": 0.01,
            "theta": -0.02,
            "implied_volatility_percent": 30,
        }
        self.signal_option_market_data(req_id)

    def signal_option_market_data(self, req_id) -> None:
        ready = self.option_market_ready_by_req_id.get(req_id)
        if ready is not None:
            ready.set()

    def cancelMktData(self, req_id) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("cancelMktData")
        self.cancelled_market_data.append(req_id)


def requested_rights(requested_contract) -> list[str]:
    """IB answers a request without a right with both calls and puts."""
    return [requested_contract.right] if requested_contract.right else ["C", "P"]


def fake_option_contract(
    requested_contract,
    strike: float,
    *,
    con_id: int,
    trading_class: str | None = None,
    right: str | None = None,
):
    right = right or requested_contract.right
    contract = us_option_contract(
        requested_contract.symbol,
        expiration=(
            f"{requested_contract.lastTradeDateOrContractMonth[:4]}-"
            f"{requested_contract.lastTradeDateOrContractMonth[4:6]}-"
            f"{requested_contract.lastTradeDateOrContractMonth[6:8]}"
        ),
        strike=strike,
        right=right,
    )
    contract.conId = con_id
    contract.tradingClass = trading_class or requested_contract.symbol
    contract.localSymbol = f"{requested_contract.symbol}{con_id}{right}"
    return contract


class TimeoutBroadOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        if contract.strike == 0:
            return

        if contract.strike not in self.contract_strikes:
            self.contract_details_ready_by_req_id[req_id].set()
            return

        self.contract_details[req_id] = [
            type(
                "ContractDetails",
                (),
                {
                    "contract": fake_option_contract(
                        contract,
                        contract.strike,
                        con_id=req_id + int(contract.strike * 100),
                    )
                },
            )()
        ]
        self.contract_details_ready_by_req_id[req_id].set()


class SharedSlotExactOptionChainIbApp(TimeoutBroadOptionChainIbApp):
    def __init__(self, contract_strikes: list[float], slots: int) -> None:
        super().__init__(contract_strikes=contract_strikes)
        self.contract_details_slots = OutstandingRequestLimiter(slots)
        self.in_flight = 0
        self.max_in_flight = 0

    def reqContractDetails(self, req_id, contract) -> None:
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)

        def respond() -> None:
            with self.lock:
                self.in_flight -= 1
            self.contract_details_slots.release(req_id)
            TimeoutBroadOptionChainIbApp.reqContractDetails(self, req_id, contract)

        threading.Timer(0.01, respond).start()


class AllContractDetailsTimeoutOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))


def deliver_ticks_later(app, delay, updates):
    def deliver() -> None:
        with app.lock:
            for req_id, values in updates.items():
                app.option_market_data[req_id].update(values)
                app.signal_option_market_data(req_id)

    threading.Timer(delay, deliver).start()