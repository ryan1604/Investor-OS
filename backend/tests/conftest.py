import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.schemas import IbStatus, PortfolioAccountSummary, PortfolioPosition
from app.stock_analysis.store import StockAnalysisStore


class FakePortfolioClient:
    def __init__(
        self,
        connected: bool = False,
        *,
        block_refresh: bool = False,
        app=None,
    ) -> None:
        self.app = app
        self.connected = connected
        self.started = False
        self.stopped = False
        self.positions_requests = 0
        self.account_summary_refreshes = 0
        self.block_refresh = block_refresh
        self.refresh_started = threading.Event()
        self.allow_refresh = threading.Event()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def get_status(self) -> IbStatus:
        return IbStatus(
            connected=self.connected,
            host="127.0.0.1",
            port=7497,
            client_id=1,
        )

    def get_positions(self) -> list[PortfolioPosition]:
        self.positions_requests += 1
        self.refresh_started.set()

        if self.block_refresh:
            self.allow_refresh.wait(timeout=1)

        if not self.connected:
            return []

        return [
            PortfolioPosition(
                account="DU1234567",
                symbol="AAPL",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
                average_cost=182.5,
            )
        ]

    def get_account_summaries(
        self,
        positions: list[PortfolioPosition],
    ) -> list[PortfolioAccountSummary]:
        if not self.connected:
            return []

        return [
            PortfolioAccountSummary(
                account="DU1234567",
                net_liquidation=125_000,
                daily_pnl=450,
                daily_pnl_percent=0.36,
                unrealized_pnl=2_400,
                market_value=18_250,
                maintenance_margin=8_000,
                excess_liquidity=117_000,
                buying_power=468_000,
                cash_total_sgd=10_000,
                cash_total_usd=20_000,
                cash_total=35_000,
            )
        ]

    def refresh_account_summaries(self) -> None:
        self.account_summary_refreshes += 1


class FakeIbOrderApp:
    def __init__(self, connected: bool = True) -> None:
        self.lock = threading.Lock()
        self.connected = connected
        self.next_order_id = 700
        self.next_execution_req_id = 90_000
        self.placed_orders = []
        self.cancelled_orders = []
        self.listeners = []
        self.registered_order_ids = []
        self.next_contract_details_req_id = 70_000
        self.contract_details = {}
        self.contract_details_ready_by_req_id = {}
        self.contract_detail_requests = []
        self.rejected_order_type = None
        self.open_order_requests = 0
        self.execution_requests = []

    def isConnected(self) -> bool:
        return self.connected

    def placeOrder(self, order_id, contract, order) -> None:
        if self.rejected_order_type == order.orderType:
            raise ValueError("combo stop orders are not supported")
        self.placed_orders.append((order_id, contract, order))

    def cancelOrder(self, order_id, manual_cancel_order_time="") -> None:
        self.cancelled_orders.append((order_id, manual_cancel_order_time))

    def add_order_status_listener(self, listener) -> None:
        self.listeners.append(listener)

    def register_submitted_order(self, order_id: int) -> None:
        self.registered_order_ids.append(order_id)

    def emit_status(self, order_id: int, status: str, **values) -> None:
        for listener in self.listeners:
            listener(order_id, status, **values)

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        contract.conId = 900_000 + len(self.contract_detail_requests)
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": contract})(),
        ]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqOpenOrders(self) -> None:
        self.open_order_requests += 1

    def reqExecutions(self, req_id, execution_filter) -> None:
        self.execution_requests.append((req_id, execution_filter))


def make_api(
    portfolio_client: FakePortfolioClient | None = None,
    *,
    options_client=None,
    stock_analysis_database_path: str | Path | None = None,
) -> FastAPI:
    explicit_portfolio_client = portfolio_client or FakePortfolioClient()

    stock_analysis_store_factory: Callable[[Settings], StockAnalysisStore] | None = None
    if stock_analysis_database_path is not None:
        stock_analysis_store_factory = lambda _settings: StockAnalysisStore(
            stock_analysis_database_path,
        )

    return create_app(
        lambda _settings: explicit_portfolio_client,
        options_client_factory=(
            (lambda _settings, _client: options_client)
            if options_client is not None
            else None
        ),
        stock_analysis_store_factory=stock_analysis_store_factory,
    )

