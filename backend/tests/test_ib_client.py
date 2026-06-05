import threading

import pytest
from ibapi.contract import Contract

from app.config import Settings
from app.ib.app import IbPortfolioApp
from app.ib.contracts import (
    clean_ib_price,
)
from app.ib.portfolio import IbPortfolioClient
from app.portfolio.domain import (
    attach_account_summaries,
    build_account_summary,
    merge_portfolio_rows,
)
from app.schemas import PortfolioAccountSummary, PortfolioPosition


class FakeIbApp:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.market_contracts: dict[int, Contract] = {}
        self.market_req_ids: dict[int, int] = {}
        self.market_req_to_con_id: dict[int, int] = {}
        self.market_data: dict[int, dict[str, float]] = {}
        self.pnl_req_ids: dict[tuple[str, int], int] = {}
        self.pnl_req_to_position_key: dict[int, tuple[str, int]] = {}
        self.pnl_data: dict[tuple[str, int], dict[str, float | None]] = {}
        self.account_pnl_req_ids: dict[str, int] = {}
        self.account_pnl_req_to_account: dict[int, str] = {}
        self.account_pnl_data: dict[str, dict[str, float | None]] = {}
        self.account_summary_values: dict[tuple[str, str, str], float] = {}
        self.pending_account_summary_values: dict[
            int,
            dict[tuple[str, str, str], float],
        ] = {}
        self.account_summary_ready_by_req_id: dict[int, threading.Event] = {}
        self.account_summary_tag_aliases_by_req_id: dict[int, dict[str, str]] = {}
        self.active_account_summary_req_id: int | None = None
        self.positions: dict[tuple[str, int, str], PortfolioPosition] = {}
        self.positions_response: list[PortfolioPosition] = []
        self.next_market_req_id = 10_000
        self.next_pnl_req_id = 30_000
        self.next_account_summary_req_id = 40_000
        self.next_account_pnl_req_id = 50_000
        self.pnl_ready = threading.Event()
        self.account_pnl_ready = threading.Event()
        self.market_data_ready = threading.Event()
        self.positions_ready = threading.Event()
        self.market_requests: list[tuple[int, Contract]] = []
        self.pnl_requests: list[tuple[int, str, str, int]] = []
        self.account_pnl_requests: list[tuple[int, str, str]] = []
        self.account_summary_requests: list[tuple[int, str, str]] = []
        self.cancelled_account_summary_requests: list[int] = []
        self.cancelled_market_requests: list[int] = []
        self.cancelled_pnl_requests: list[int] = []
        self.cancelled_account_pnl_requests: list[int] = []
        self.cancelled_positions = 0
        self.positions_requests = 0
        self.disconnects = 0
        self.ib_calls_inside_lock: list[str] = []

    def isConnected(self) -> bool:
        return True

    def reqMktData(
        self,
        req_id: int,
        contract: Contract,
        generic_tick_list: str,
        snapshot: bool,
        regulatory_snapshot: bool,
        mkt_data_options: list,
    ) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("reqMktData")
        self.market_requests.append((req_id, contract))
        self.market_data_ready.set()

    def cancelMktData(self, req_id: int) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("cancelMktData")
        self.cancelled_market_requests.append(req_id)

    def reqPositions(self) -> None:
        self.positions_requests += 1
        self.positions = {
            (position.account, position.con_id or 0, position.local_symbol or ""): position
            for position in self.positions_response
        }
        self.positions_ready.set()

    def cancelPositions(self) -> None:
        self.cancelled_positions += 1

    def disconnect(self) -> None:
        self.disconnects += 1

    def reqPnLSingle(
        self,
        req_id: int,
        account: str,
        model_code: str,
        con_id: int,
    ) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("reqPnLSingle")
        self.pnl_requests.append((req_id, account, model_code, con_id))
        self.pnl_ready.set()

    def cancelPnLSingle(self, req_id: int) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("cancelPnLSingle")
        self.cancelled_pnl_requests.append(req_id)

    def reqPnL(self, req_id: int, account: str, model_code: str) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("reqPnL")
        self.account_pnl_requests.append((req_id, account, model_code))
        self.account_pnl_ready.set()

    def cancelPnL(self, req_id: int) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("cancelPnL")
        self.cancelled_account_pnl_requests.append(req_id)

    def reqAccountSummary(
        self,
        req_id: int,
        group_name: str,
        tags: str,
    ) -> None:
        self.account_summary_requests.append((req_id, group_name, tags))
        self.accountSummaryEnd(req_id)

    def cancelAccountSummary(self, req_id: int) -> None:
        self.cancelled_account_summary_requests.append(req_id)

    def start_account_summary_request(
        self,
        req_id: int,
        *,
        initial_values: dict[tuple[str, str, str], float] | None = None,
        tag_aliases: dict[str, str] | None = None,
    ) -> tuple[threading.Event, int | None]:
        superseded_req_id = self.active_account_summary_req_id
        ready = threading.Event()
        self.pending_account_summary_values[req_id] = dict(
            self.account_summary_values
            if initial_values is None
            else initial_values
        )
        self.account_summary_ready_by_req_id[req_id] = ready
        self.account_summary_tag_aliases_by_req_id[req_id] = tag_aliases or {}
        self.active_account_summary_req_id = req_id
        return ready, superseded_req_id

    def accountSummaryEnd(self, req_id: int) -> None:
        if req_id != self.active_account_summary_req_id:
            return

        self.account_summary_values = self.pending_account_summary_values.pop(req_id)
        self.active_account_summary_req_id = None
        self.account_summary_tag_aliases_by_req_id.pop(req_id, None)
        self.account_summary_ready_by_req_id.pop(req_id).set()

    def abandon_account_summary_request(self, req_id: int) -> None:
        self.pending_account_summary_values.pop(req_id, None)
        self.account_summary_ready_by_req_id.pop(req_id, None)
        self.account_summary_tag_aliases_by_req_id.pop(req_id, None)
        if req_id == self.active_account_summary_req_id:
            self.active_account_summary_req_id = None


def contract(con_id: int, symbol: str, sec_type: str) -> Contract:
    next_contract = Contract()
    next_contract.conId = con_id
    next_contract.symbol = symbol
    next_contract.secType = sec_type
    return next_contract


def test_subscribe_market_data_requests_streaming_data_for_positions():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    option_contract = contract(1, "HIMS", "OPT")
    stock_contract = contract(2, "HIMS", "STK")
    app.market_contracts = {
        option_contract.conId: option_contract,
        stock_contract.conId: stock_contract,
    }
    client.app = app

    client._subscribe_market_data()
    client._subscribe_market_data()

    assert [request[1].secType for request in app.market_requests] == ["OPT", "STK"]
    assert app.ib_calls_inside_lock == []


def test_get_positions_uses_raw_position_feed_without_account_updates(caplog):
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    app.positions_response = [
        PortfolioPosition(
            account="DU1234567",
            con_id=123,
            symbol="AMD",
            sec_type="STK",
            exchange="NASDAQ",
            currency="USD",
            quantity=100,
            average_cost=80,
        )
    ]
    client.app = app

    with caplog.at_level("INFO", logger="app.ib.portfolio"):
        positions = client.get_positions()

    assert app.cancelled_positions == 0
    assert app.market_contracts[123].symbol == "AMD"
    assert positions[0].cost_basis == 8_000
    assert positions[0].average_price == 80

    client.get_positions()

    assert app.cancelled_positions == 0
    assert app.positions_requests == 1
    assert "Portfolio positions refreshed positions=1" in caplog.text
    assert "position_pnl_ms=" in caplog.text
    assert "DU1234567" not in caplog.text
    assert "AMD" not in caplog.text


def test_tick_price_marks_market_data_ready():
    app = IbPortfolioApp()
    app.market_req_to_con_id[10_000] = 123

    app.tickPrice(10_000, 4, 110, None)

    assert app.market_data_ready.is_set()


def test_stop_cancels_live_position_subscription():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    client.app = app

    client.get_positions()
    client.stop()

    assert app.cancelled_positions == 1
    assert app.disconnects == 1


def test_position_callback_removes_closed_position_from_cache():
    app = IbPortfolioApp()
    stock_contract = contract(123, "AMD", "STK")

    app.position("DU1234567", stock_contract, 100, 80)
    app.position("DU1234567", stock_contract, 0, 80)

    assert app.positions == {}


def test_delayed_option_prices_and_volume_are_stored():
    app = IbPortfolioApp()
    app.option_market_req_to_key[90_000] = (100, "C")

    app.tickPrice(90_000, 66, 1.2, None)
    app.tickPrice(90_000, 67, 1.4, None)
    app.tickSize(90_000, 69, 10)
    app.tickSize(90_000, 70, 20)
    app.tickSize(90_000, 29, 25)

    assert app.option_market_data[90_000] == {
        "bid": 1.2,
        "ask": 1.4,
        "bid_size": 10,
        "ask_size": 20,
        "volume": 25,
    }


def test_option_computation_allows_missing_ib_values():
    app = IbPortfolioApp()
    app.option_market_req_to_key[90_000] = (100, "C")

    app.tickOptionComputation(
        90_000,
        13,
        0,
        None,
        0.45,
        None,
        None,
        None,
        None,
        -0.02,
        None,
    )

    assert app.option_market_data[90_000] == {
        "delta": 0.45,
        "theta": -0.02,
    }
    assert app.option_market_data_ready.is_set()


def test_option_computation_preserves_values_from_partial_ticks_and_scales_iv():
    app = IbPortfolioApp()
    app.option_market_req_to_key[90_000] = (100, "C")

    app.tickOptionComputation(
        90_000,
        13,
        0,
        0.42,
        0.45,
        1.25,
        None,
        0.01,
        None,
        -0.02,
        None,
    )
    app.tickOptionComputation(
        90_000,
        12,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert app.option_market_data[90_000] == {
        "implied_volatility_percent": 42,
        "delta": 0.45,
        "gamma": 0.01,
        "theta": -0.02,
        "model_price": 1.25,
    }


def test_historical_no_data_error_releases_waiting_request():
    app = IbPortfolioApp()
    app.historical_bars[60_000] = []
    ready = threading.Event()
    app.historical_data_ready_by_req_id[60_000] = ready

    app.error(
        60_000,
        162,
        "Historical Market Data Service error message:HMDS query returned no data",
    )

    assert ready.is_set()


def test_invalid_contract_error_releases_waiting_historical_request():
    app = IbPortfolioApp()
    ready = threading.Event()
    app.historical_data_ready_by_req_id[60_000] = ready

    app.error(
        60_000,
        200,
        "No security definition has been found for the request",
    )

    assert ready.is_set()
    assert app.request_errors_by_req_id[60_000] == (
        200,
        "No security definition has been found for the request",
    )


def test_options_callbacks_release_only_their_request_waiters():
    app = IbPortfolioApp()
    historical_ready = threading.Event()
    other_historical_ready = threading.Event()
    contract_ready = threading.Event()
    other_contract_ready = threading.Event()
    metadata_ready = threading.Event()
    other_metadata_ready = threading.Event()
    app.historical_data_ready_by_req_id = {
        60_000: historical_ready,
        60_001: other_historical_ready,
    }
    app.contract_details_ready_by_req_id = {
        70_000: contract_ready,
        70_001: other_contract_ready,
    }
    app.option_metadata_ready_by_req_id = {
        80_000: metadata_ready,
        80_001: other_metadata_ready,
    }

    app.historicalDataEnd(60_000, "", "")
    app.contractDetailsEnd(70_000)
    app.securityDefinitionOptionParameterEnd(80_000)

    assert historical_ready.is_set()
    assert contract_ready.is_set()
    assert metadata_ready.is_set()
    assert not other_historical_ready.is_set()
    assert not other_contract_ready.is_set()
    assert not other_metadata_ready.is_set()


def test_late_contract_details_callback_does_not_recreate_timed_out_request():
    app = IbPortfolioApp()

    app.contractDetails(70_000, object())

    assert app.contract_details == {}


def test_zero_prices_are_treated_as_missing_market_data():
    app = IbPortfolioApp()
    app.market_req_to_con_id[10_000] = 123

    app.tickPrice(10_000, 4, 0, None)

    assert clean_ib_price(0) is None
    assert app.market_data == {}


def test_merge_market_data_does_not_calculate_pnl_without_ib_pnl_data():
    client = IbPortfolioClient(Settings())
    client.app.market_data[123] = {"last": 110, "close": 100}

    positions = client._merge_market_data(
        [
            PortfolioPosition(
                account="DU1234567",
                con_id=123,
                symbol="AMD",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
                average_cost=80,
                multiplier=None,
                net_liquidity=100_000,
            )
        ]
    )

    assert positions[0].pnl is None
    assert positions[0].pnl_percent is None
    assert positions[0].unrealized_pnl is None


def test_subscribe_pnl_requests_single_position_pnl():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    client.app = app

    client._subscribe_pnl(
        [
            PortfolioPosition(
                account="DU1234567",
                con_id=123,
                symbol="AMD",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
                average_cost=80,
            )
        ]
    )
    client._subscribe_pnl(
        [
            PortfolioPosition(
                account="DU1234567",
                con_id=123,
                symbol="AMD",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
                average_cost=80,
            )
        ]
    )

    assert app.pnl_requests == [(30_000, "DU1234567", "", 123)]
    assert app.ib_calls_inside_lock == []


def test_subscribe_account_pnl_requests_each_active_account():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    client.app = app

    client._subscribe_account_pnl(["U19793128", "U6985190"])
    client._subscribe_account_pnl(["U19793128", "U6985190"])

    assert sorted(request[1] for request in app.account_pnl_requests) == [
        "U19793128",
        "U6985190",
    ]
    assert app.ib_calls_inside_lock == []


def test_new_pnl_stream_populates_position_asynchronously():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    client.app = app
    position = PortfolioPosition(
        account="DU1234567",
        con_id=123,
        symbol="AMD",
        sec_type="STK",
        exchange="NASDAQ",
        currency="USD",
        quantity=100,
        average_cost=80,
    )

    client._subscribe_pnl([position])
    before_callback = client._merge_market_data([position])
    app.pnl_data[("DU1234567", 123)] = {
        "daily_pnl": 900,
        "unrealized_pnl": 2_800,
        "realized_pnl": 50,
        "market_value": 11_000,
    }
    after_callback = client._merge_market_data([position])

    assert before_callback[0].market_value is None
    assert before_callback[0].pnl is None
    assert after_callback[0].market_value == 11_000
    assert after_callback[0].pnl == 900


def test_subscribe_pnl_cancels_stale_position_stream():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    app.pnl_req_ids[("DU1234567", 123)] = 30_000
    app.pnl_req_to_position_key[30_000] = ("DU1234567", 123)
    app.pnl_data[("DU1234567", 123)] = {"daily_pnl": 900}
    client.app = app

    client._subscribe_pnl([])

    assert app.pnl_req_ids == {}
    assert app.pnl_req_to_position_key == {}
    assert app.pnl_data == {}
    assert app.cancelled_pnl_requests == [30_000]
    assert app.ib_calls_inside_lock == []


def test_subscribe_account_pnl_cancels_stale_account_stream():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    app.account_pnl_req_ids["DU1234567"] = 50_000
    app.account_pnl_req_to_account[50_000] = "DU1234567"
    app.account_pnl_data["DU1234567"] = {"daily_pnl": 900}
    client.app = app

    client._subscribe_account_pnl([])

    assert app.account_pnl_req_ids == {}
    assert app.account_pnl_req_to_account == {}
    assert app.account_pnl_data == {}
    assert app.cancelled_account_pnl_requests == [50_000]
    assert app.ib_calls_inside_lock == []


def test_merge_market_data_prefers_ib_single_position_pnl():
    market_data = {123: {"last": 110, "close": 100}}
    pnl_data = {
        ("DU1234567", 123): {
            "daily_pnl": 900,
            "unrealized_pnl": 2800,
            "realized_pnl": 50,
            "market_value": 11_000,
        }
    }

    positions = attach_account_summaries(
        merge_portfolio_rows(
            [
                PortfolioPosition(
                    account="DU1234567",
                    con_id=123,
                    symbol="AMD",
                    sec_type="STK",
                    exchange="NASDAQ",
                    currency="USD",
                    quantity=100,
                    average_cost=80,
                )
            ],
            market_data,
            pnl_data,
        ),
        [
            PortfolioAccountSummary(
                account="DU1234567",
                net_liquidation=100_000,
            )
        ],
    )

    assert positions[0].pnl == 900
    assert positions[0].pnl_percent == pytest.approx(0.9)
    assert positions[0].unrealized_pnl == 2800
    assert positions[0].unrealized_pnl_percent == 35
    assert positions[0].realized_pnl == 50
    assert positions[0].market_value == 11_000
    assert positions[0].net_liquidity_percent == 11


def test_client_merge_market_data_snapshots_app_state():
    client = IbPortfolioClient(Settings())
    client.app.market_data[123] = {"last": 110}
    client.app.pnl_data[("DU1234567", 123)] = {
        "daily_pnl": 900,
        "unrealized_pnl": None,
        "realized_pnl": None,
        "market_value": None,
    }

    positions = client._merge_market_data(
        [
            PortfolioPosition(
                account="DU1234567",
                con_id=123,
                symbol="AMD",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
                average_cost=80,
            )
        ]
    )

    assert positions[0].last_price == 110
    assert positions[0].pnl == 900


def test_merge_market_data_does_not_use_removed_account_update_values():
    positions = merge_portfolio_rows(
        [
            PortfolioPosition(
                account="U6985190",
                con_id=123,
                symbol="SOFI",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=761.6256,
                average_cost=17.77,
                last_price=18.08,
                unrealized_pnl=230.82,
                market_value=13_770,
                cost_basis=13_534.086912,
                average_price=17.77,
            )
        ],
        {},
        {},
    )

    assert positions[0].last_price is None
    assert positions[0].unrealized_pnl is None
    assert positions[0].market_value is None
    assert positions[0].cost_basis == pytest.approx(13_534.086912)
    assert positions[0].average_price == 17.77


def test_merge_market_data_does_not_derive_market_value_from_last_price():
    positions = merge_portfolio_rows(
        [
            PortfolioPosition(
                account="U6985190",
                con_id=123,
                symbol="SOFI",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=761.6256,
                average_cost=23.81,
            )
        ],
        {123: {"last": 18.08}},
        {},
    )

    assert positions[0].last_price == 18.08
    assert positions[0].market_value is None


def test_merge_market_data_does_not_derive_change_percent_from_daily_pnl():
    positions = merge_portfolio_rows(
        [
            PortfolioPosition(
                account="DU1234567",
                con_id=123,
                symbol="SOFI",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=594.4595,
                average_cost=17.77,
                last_price=18.08,
            )
        ],
        {},
        {
            ("DU1234567", 123): {
                "daily_pnl": 707.41,
                "unrealized_pnl": 230.82,
                "realized_pnl": None,
                "market_value": 10_795.38,
            }
        },
    )

    assert positions[0].change_percent is None


def test_invalid_ib_pnl_values_stay_missing():
    app = IbPortfolioApp()
    app.pnl_req_to_position_key[30_000] = ("DU1234567", 123)

    app.pnlSingle(30_000, 100, 1e101, 1e101, 1e101, 1e101)

    assert app.pnl_data[("DU1234567", 123)] == {
        "position": 100,
        "daily_pnl": None,
        "unrealized_pnl": None,
        "realized_pnl": None,
        "market_value": None,
    }


def test_account_pnl_callback_records_account_daily_pnl():
    app = IbPortfolioApp()
    app.account_pnl_req_to_account[50_000] = "U6985190"

    app.pnl(50_000, 123.45, -50, 10)

    assert app.account_pnl_data["U6985190"] == {
        "daily_pnl": 123.45,
        "unrealized_pnl": -50,
        "realized_pnl": 10,
    }
    assert app.account_pnl_ready.is_set()


def test_account_summary_uses_summary_feed_and_account_pnl_stream():
    account_summary_values = {
        ("DU1234567", "NetLiquidation", "USD"): 100_000,
        ("DU1234567", "MaintMarginReq", "USD"): 12_000,
        ("DU1234567", "ExcessLiquidity", "USD"): 88_000,
        ("DU1234567", "BuyingPower", "USD"): 352_000,
        ("DU1234567", "cash_total_sgd", "SGD"): 3_000,
        ("DU1234567", "cash_total_usd", "USD"): 4_000,
        ("DU1234567", "cash_total", "BASE"): 8_500,
    }
    account_pnl_data = {
        "DU1234567": {
            "daily_pnl": 200,
            "unrealized_pnl": 2_000,
            "realized_pnl": 0,
        }
    }

    summary = build_account_summary(
        "DU1234567",
        account_summary_values,
        account_pnl_data,
    )

    assert summary.net_liquidation == 100_000
    assert summary.daily_pnl == 200
    assert summary.daily_pnl_percent == pytest.approx(0.2)
    assert summary.unrealized_pnl == 2_000
    assert summary.market_value is None
    assert summary.maintenance_margin == 12_000
    assert summary.excess_liquidity == 88_000
    assert summary.buying_power == 352_000
    assert summary.currency == "USD"
    assert summary.cash_total_sgd == 3_000
    assert summary.cash_total_usd == 4_000
    assert summary.cash_total == 8_500


def test_account_summary_refresh_requests_all_accounts_from_ib_summary_feed(caplog):
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    app.account_summary_values = {
        ("U19793128", "NetLiquidation", "USD"): 29_375.08,
        ("U19793128", "BuyingPower", "USD"): 106_502.36,
        ("U6985190", "NetLiquidation", "USD"): 11_260.36,
        ("U6985190", "BuyingPower", "USD"): 22_333.72,
    }
    client.app = app

    with caplog.at_level("INFO", logger="app.ib.portfolio"):
        client.refresh_account_summaries()
    summaries = client.get_account_summaries(
        [
            PortfolioPosition(
                account="U19793128",
                con_id=123,
                symbol="AMD",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
            ),
            PortfolioPosition(
                account="U6985190",
                con_id=456,
                symbol="SOFI",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
            ),
        ]
    )

    summaries_by_account = {summary.account: summary for summary in summaries}

    assert app.account_summary_requests[0][1] == "All"
    assert "NetLiquidation" in app.account_summary_requests[0][2]
    assert [request[2] for request in app.account_summary_requests] == [
        "BuyingPower,ExcessLiquidity,GrossPositionValue,MaintMarginReq,NetLiquidation",
        "$LEDGER:SGD",
        "$LEDGER:USD",
        "$LEDGER",
    ]
    assert app.cancelled_account_summary_requests == [
        40_000,
        40_001,
        40_002,
        40_003,
    ]
    assert summaries_by_account["U19793128"].net_liquidation == 29_375.08
    assert summaries_by_account["U6985190"].net_liquidation == 11_260.36
    assert summaries_by_account["U6985190"].buying_power == 22_333.72
    assert "Portfolio account summary feed refreshed total_ms=" in caplog.text
    assert "U19793128" not in caplog.text
    assert "U6985190" not in caplog.text


def test_account_summary_cycle_replaces_omitted_values():
    app = IbPortfolioApp()

    app.start_account_summary_request(40_000)
    app.accountSummary(40_000, "DU1234567", "NetLiquidation", "100000", "USD")
    app.accountSummary(40_000, "DU1234567", "BuyingPower", "352000", "USD")
    app.accountSummaryEnd(40_000)
    app.start_account_summary_request(40_001)
    app.accountSummary(40_001, "DU1234567", "NetLiquidation", "90000", "USD")
    app.accountSummaryEnd(40_001)

    assert app.account_summary_values == {
        ("DU1234567", "NetLiquidation", "USD"): 90_000,
    }


def test_account_summary_ledger_callbacks_use_request_source_alias():
    app = IbPortfolioApp()

    app.start_account_summary_request(
        40_000,
        tag_aliases={"TotalCashBalance": "cash_total_sgd"},
    )
    app.accountSummary(40_000, "DU1234567", "TotalCashBalance", "3000", "SGD")
    app.accountSummaryEnd(40_000)
    app.start_account_summary_request(
        40_001,
        initial_values=app.account_summary_values,
        tag_aliases={"TotalCashBalance": "cash_total"},
    )
    app.accountSummary(40_001, "DU1234567", "TotalCashBalance", "8500", "BASE")
    app.accountSummaryEnd(40_001)

    assert app.account_summary_values == {
        ("DU1234567", "cash_total_sgd", "SGD"): 3_000,
        ("DU1234567", "cash_total", "BASE"): 8_500,
    }


def test_late_account_summary_callbacks_do_not_complete_or_mutate_new_cycle():
    app = IbPortfolioApp()

    first_ready, _ = app.start_account_summary_request(40_000)
    app.accountSummary(40_000, "DU1234567", "NetLiquidation", "100000", "USD")
    second_ready, superseded_req_id = app.start_account_summary_request(40_001)
    app.accountSummaryEnd(40_000)
    app.accountSummary(40_000, "DU1234567", "BuyingPower", "352000", "USD")
    app.accountSummary(40_001, "DU1234567", "NetLiquidation", "90000", "USD")

    assert superseded_req_id == 40_000
    assert not first_ready.is_set()
    assert not second_ready.is_set()

    app.accountSummaryEnd(40_001)

    assert second_ready.is_set()
    assert app.account_summary_values == {
        ("DU1234567", "NetLiquidation", "USD"): 90_000,
    }


def test_get_account_summaries_includes_flat_accounts_from_summary_feed():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    app.account_summary_values = {
        ("DU1234567", "NetLiquidation", "USD"): 100_000,
    }
    client.app = app

    summaries = client.get_account_summaries([])

    assert [summary.account for summary in summaries] == ["DU1234567"]
    assert summaries[0].net_liquidation == 100_000
    assert app.account_pnl_requests == [(50_000, "DU1234567", "")]


def test_register_market_contracts_for_raw_positions():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    client.app = app

    client._register_market_contracts(
        [
            PortfolioPosition(
                account="U6985190",
                con_id=456,
                symbol="SOFI",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
            )
        ]
    )

    assert app.market_contracts[456].symbol == "SOFI"
    assert app.market_contracts[456].exchange == "NASDAQ"


def test_register_market_contracts_cancels_stale_streams():
    client = IbPortfolioClient(Settings())
    app = FakeIbApp()
    app.market_contracts[123] = contract(123, "AMD", "STK")
    app.market_req_ids[123] = 10_000
    app.market_req_to_con_id[10_000] = 123
    app.market_data[123] = {"last": 110}
    client.app = app

    client._register_market_contracts([])

    assert app.market_contracts == {}
    assert app.market_req_ids == {}
    assert app.market_req_to_con_id == {}
    assert app.market_data == {}
    assert app.cancelled_market_requests == [10_000]
    assert app.ib_calls_inside_lock == []


def test_order_callbacks_forward_normalized_status_payloads():
    app = IbPortfolioApp()
    updates = []
    app.add_order_status_listener(
        lambda order_id, status, **values: updates.append(
            (order_id, status, values),
        ),
    )

    app.nextValidId(900)
    app.orderStatus(
        900,
        "Submitted",
        2,
        3,
        1.25,
        12345,
        0,
        1.25,
        1,
        "",
        0,
    )

    assert app.next_order_id == 900
    assert updates == [
        (
            900,
            "Submitted",
            {
                "filled": 2,
                "remaining": 3,
                "avg_fill_price": 1.25,
                "perm_id": 12345,
                "parent_order_id": None,
                "rejection_message": None,
            },
        )
    ]


def test_registered_order_error_forwards_rejection_message(caplog):
    app = IbPortfolioApp()
    updates = []
    app.add_order_status_listener(
        lambda order_id, status, **values: updates.append(
            (order_id, status, values),
        ),
    )
    app.register_submitted_order(901)

    with caplog.at_level("WARNING", logger="app.ib.app"):
        app.error(901, 201, "Order rejected")

    assert updates == [
        (
            901,
            "Inactive",
            {
                "filled": None,
                "remaining": None,
                "avg_fill_price": None,
                "perm_id": None,
                "parent_order_id": None,
                "rejection_message": "Order rejected",
            },
        )
    ]
    assert "Order rejected" in caplog.text


def test_open_order_callback_forwards_account_and_parent_id():
    app = IbPortfolioApp()
    updates = []
    app.add_order_status_listener(
        lambda order_id, status, **values: updates.append(
            (order_id, status, values),
        ),
    )
    order = type(
        "Order",
        (),
        {
            "account": "DU1234567",
            "totalQuantity": 2,
            "permId": 123,
            "parentId": 900,
        },
    )()
    order_state = type("OrderState", (), {"status": "Submitted"})()

    app.openOrder(901, contract(901, "AAPL", "OPT"), order, order_state)

    assert updates == [
        (
            901,
            "Submitted",
            {
                "filled": 0,
                "remaining": 2,
                "avg_fill_price": None,
                "perm_id": 123,
                "parent_order_id": 900,
                "rejection_message": None,
                "account": "DU1234567",
            },
        )
    ]


def test_exec_details_callback_forwards_filled_order_payload():
    app = IbPortfolioApp()
    updates = []
    app.add_order_status_listener(
        lambda order_id, status, **values: updates.append(
            (order_id, status, values),
        ),
    )
    execution = type(
        "Execution",
        (),
        {
            "orderId": 902,
            "shares": 3,
            "price": 1.25,
            "permId": 456,
            "acctNumber": "DU1234567",
        },
    )()

    app.execDetails(90_000, contract(902, "AAPL", "OPT"), execution)

    assert updates == [
        (
            902,
            "Filled",
            {
                "filled": 3,
                "remaining": 0,
                "avg_fill_price": 1.25,
                "perm_id": 456,
                "parent_order_id": None,
                "rejection_message": None,
                "account": "DU1234567",
            },
        )
    ]
