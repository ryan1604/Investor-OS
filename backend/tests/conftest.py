import threading
import tempfile
from pathlib import Path

from fastapi import FastAPI

from app.config import Settings
from app.main import AppOverrides, create_app
from app.options.client import OptionsDataUnavailable
from app.options_screeners.service import OptionsScreenerService
from app.schemas import IbStatus, PortfolioAccountSummary, PortfolioPosition


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
        self.execution_listeners = []
        self.execution_end_listeners = []
        self.completed_order_listeners = []
        self.completed_orders_end_listeners = []
        self.open_order_end_listeners = []
        self.registered_order_ids = []
        self.next_contract_details_req_id = 70_000
        self.contract_details = {}
        self.contract_details_ready_by_req_id = {}
        self.contract_details_by_con_id = {}
        self.contract_detail_requests = []
        self.rejected_order_type = None
        self.open_order_requests = 0
        self.all_open_order_requests = 0
        self.auto_open_order_requests = []
        self.execution_requests = []
        self.completed_order_requests = []

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

    def add_execution_listener(self, listener) -> None:
        self.execution_listeners.append(listener)

    def add_execution_end_listener(self, listener) -> None:
        self.execution_end_listeners.append(listener)

    def add_completed_order_listener(self, listener) -> None:
        self.completed_order_listeners.append(listener)

    def add_completed_orders_end_listener(self, listener) -> None:
        self.completed_orders_end_listeners.append(listener)

    def add_open_order_end_listener(self, listener) -> None:
        self.open_order_end_listeners.append(listener)

    def register_submitted_order(self, order_id: int) -> None:
        self.registered_order_ids.append(order_id)

    def emit_status(self, order_id: int, status: str, **values) -> None:
        for listener in self.listeners:
            listener(order_id, status, **values)

    def emit_execution(self, **values) -> None:
        for listener in self.execution_listeners:
            listener(req_id=90_000, **values)

    def emit_execution_end(self, req_id: int = 90_000) -> None:
        for listener in self.execution_end_listeners:
            listener(req_id)

    def emit_completed_order(self, contract, order, order_state) -> None:
        for listener in self.completed_order_listeners:
            listener(contract=contract, order=order, order_state=order_state)

    def emit_completed_orders_end(self) -> None:
        for listener in self.completed_orders_end_listeners:
            listener()

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        contract = self.contract_details_by_con_id.get(
            getattr(contract, "conId", 0),
            contract,
        )
        if not getattr(contract, "conId", 0):
            contract.conId = 900_000 + len(self.contract_detail_requests)
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": contract})(),
        ]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqOpenOrders(self) -> None:
        self.open_order_requests += 1

    def reqAllOpenOrders(self) -> None:
        self.all_open_order_requests += 1

    def reqAutoOpenOrders(self, auto_bind) -> None:
        self.auto_open_order_requests.append(auto_bind)

    def emit_open_order_end(self) -> None:
        for listener in self.open_order_end_listeners:
            listener()

    def reqExecutions(self, req_id, execution_filter) -> None:
        self.execution_requests.append((req_id, execution_filter))

    def reqCompletedOrders(self, api_only) -> None:
        self.completed_order_requests.append(api_only)


class FakeUnavailableOptionsClient:
    def get_analysis(self, ticker: str):
        raise OptionsDataUnavailable(
            "Options historical data provider is not configured."
        )

    def get_underlying_price(self, ticker: str):
        raise OptionsDataUnavailable("Underlying price is unavailable.")

    def get_expirations(self, ticker: str):
        raise OptionsDataUnavailable(
            "Options metadata provider is not configured."
        )

    def get_chain(self, ticker: str, expiration: str):
        raise OptionsDataUnavailable("Options chain provider is not configured.")

    def stream_chain(self, ticker: str, expiration: str, *, stop_event):
        raise OptionsDataUnavailable(
            "Options chain stream provider is not configured."
        )

    def stream_chart(self, ticker: str, *, stop_event):
        raise OptionsDataUnavailable(
            "Options chart stream provider is not configured."
        )


def make_api(
    portfolio_client: FakePortfolioClient | None = None,
    *,
    options_client=None,
    stock_analysis_database_path: str | Path | None = None,
    portfolio_chart_values_database_path: str | Path | None = None,
    options_trade_tracker_database_path: str | Path | None = None,
    orders_database_path: str | Path | None = None,
    options_screeners_database_path: str | Path | None = None,
    options_screener_scan_service: OptionsScreenerService | None = None,
) -> FastAPI:
    explicit_portfolio_client = portfolio_client or FakePortfolioClient()
    data_dir = Path(tempfile.mkdtemp())
    settings = make_test_settings(
        data_dir,
        stock_analysis_database_path=stock_analysis_database_path,
        portfolio_chart_values_database_path=portfolio_chart_values_database_path,
        options_trade_tracker_database_path=options_trade_tracker_database_path,
        orders_database_path=orders_database_path,
        options_screeners_database_path=options_screeners_database_path,
    )

    return create_app(
        settings,
        AppOverrides(
            client=explicit_portfolio_client,
            options_client=options_client or FakeUnavailableOptionsClient(),
            options_screener_scan_service=options_screener_scan_service,
        ),
    )


def make_test_settings(
    data_dir: str | Path,
    *,
    stock_analysis_database_path: str | Path | None = None,
    portfolio_chart_values_database_path: str | Path | None = None,
    options_trade_tracker_database_path: str | Path | None = None,
    orders_database_path: str | Path | None = None,
    options_screeners_database_path: str | Path | None = None,
    earnings_watch_database_path: str | Path | None = None,
) -> Settings:
    data_path = Path(data_dir)
    return Settings(
        stock_analysis_database_path=str(
            stock_analysis_database_path or data_path / "stock_analysis.sqlite3",
        ),
        portfolio_chart_values_database_path=str(
            portfolio_chart_values_database_path
            or data_path / "portfolio_chart_values.sqlite3",
        ),
        options_trade_trackers_database_path=str(
            options_trade_tracker_database_path
            or data_path / "options_trade_trackers.sqlite3",
        ),
        orders_database_path=str(orders_database_path or data_path / "orders.sqlite3"),
        options_screeners_database_path=str(
            options_screeners_database_path or data_path / "options_screeners.sqlite3",
        ),
        earnings_watch_database_path=str(
            earnings_watch_database_path or data_path / "earnings_watch.sqlite3",
        ),
    )
