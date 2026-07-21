import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from ibapi.contract import ComboLeg, Contract
from ibapi.execution import ExecutionFilter
from ibapi.order import Order

from app.orders.service import OrderService
from app.orders.store import OrderStore
from app.schemas import OrderRecord, StockOrderRequest
from conftest import FakeIbOrderApp, FakePortfolioClient, make_api


US_MARKET_TIME_ZONE = ZoneInfo("America/New_York")


def stock_order_payload():
    return {
        "order_kind": "stock",
        "account": "du1234567",
        "ticker": "aapl",
        "action": "BUY",
        "quantity": 10,
        "order_type": "LIMIT",
        "limit_price": 190.5,
        "time_in_force": "GTC",
    }


def create_orders_test_app(ib_app: FakeIbOrderApp, *, orders_database_path=None):
    return make_api(
        FakePortfolioClient(connected=ib_app.connected, app=ib_app),
        orders_database_path=orders_database_path,
    )


def test_order_preview_returns_confirmation_ready_stock_payload():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        response = client.post("/orders/preview", json=stock_order_payload())

    assert response.status_code == 200
    assert response.json()["account"] == "DU1234567"
    assert response.json()["order_kind"] == "stock"
    assert response.json()["summary"] == "BUY 10 share(s) AAPL"
    assert response.json()["time_in_force"] == "GTC"
    assert response.json()["request"]["ticker"] == "AAPL"


def test_transmit_stock_order_places_ib_order_for_explicit_account():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=stock_order_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["order"]["order_id"] == 700
    assert payload["order"]["status"] == "submitted"
    assert payload["order"]["is_open"] is True
    assert payload["order"]["is_current_day_history"] is False
    assert payload["order"]["account"] == "DU1234567"
    assert ib_app.registered_order_ids == [700]
    assert ib_app.placed_orders[0][0] == 700
    assert ib_app.placed_orders[0][1].symbol == "AAPL"
    assert ib_app.placed_orders[0][2].account == "DU1234567"
    assert ib_app.placed_orders[0][2].orderType == "LMT"
    assert ib_app.placed_orders[0][2].tif == "GTC"
    assert ib_app.placed_orders[0][2].eTradeOnly is False
    assert ib_app.placed_orders[0][2].firmQuoteOnly is False


def test_startup_reconciles_ib_open_orders_and_executions():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api):
        pass

    assert ib_app.auto_open_order_requests == [True]
    assert ib_app.open_order_requests == 1
    assert ib_app.all_open_order_requests == 0
    assert len(ib_app.execution_requests) == 1
    assert ib_app.completed_order_requests == [False]
    req_id, execution_filter = ib_app.execution_requests[0]
    assert req_id == 90_000
    assert ib_app.next_execution_req_id == 90_001
    assert isinstance(execution_filter, ExecutionFilter)


def test_reconcile_endpoint_requests_ib_open_orders():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        ib_app.auto_open_order_requests.clear()
        ib_app.open_order_requests = 0
        ib_app.all_open_order_requests = 0
        response = client.post("/orders/reconcile")

    assert response.status_code == 200
    assert response.json() == {"message": "Requested IB open-order reconciliation."}
    assert ib_app.auto_open_order_requests == [True]
    assert ib_app.open_order_requests == 1
    assert ib_app.all_open_order_requests == 0


def test_open_order_reconstruction_does_not_block_on_combo_contract_details():
    ib_app = DelayedContractDetailsIbApp()
    service = OrderService(ib_app)
    contract = Contract()
    contract.secType = "BAG"
    contract.symbol = "AAPL"
    leg = ComboLeg()
    leg.conId = 12345
    leg.action = "BUY"
    leg.ratio = 1
    contract.comboLegs = [leg]
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = 1.25
    order.tif = "GTC"
    order.clientId = 0

    started_at = time.monotonic()
    service.handle_ib_open_order(
        701,
        "Submitted",
        contract=contract,
        order=order,
        order_state=type("OrderState", (), {"status": "Submitted"})(),
        filled=0,
        remaining=1,
        perm_id=12345,
        parent_order_id=None,
        account="DU1234567",
    )

    assert time.monotonic() - started_at < 0.5
    assert service.snapshot()[0].editable is True
    wait_until(lambda: ib_app.contract_detail_requests)
    assert [request[1].conId for request in ib_app.contract_detail_requests] == [12345]
    assert [request[1].exchange for request in ib_app.contract_detail_requests] == [
        "SMART",
    ]
    assert [request[1].currency for request in ib_app.contract_detail_requests] == [
        "USD",
    ]
    assert [request[1].symbol for request in ib_app.contract_detail_requests] == [
        "AAPL",
    ]
    ib_app.complete_next_contract_details(option_contract(con_id=12345, strike=200))
    wait_until(lambda: service.snapshot()[0].preview.request.order_kind == "option_strategy")
    order = service.snapshot()[0]
    assert order.editable is True
    assert order.preview.request.order_kind == "option_strategy"


def test_order_store_restores_submitted_records_after_restart(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        response = client.post("/orders/transmit", json=stock_order_payload())

    assert response.status_code == 200

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        snapshot = client.get("/orders")
        amend_response = client.patch(
            "/orders/700",
            json={
                "account": "DU1234567",
                "limit_price": 191.25,
            },
        )

    assert snapshot.status_code == 200
    assert snapshot.json()[0]["order_id"] == 700
    assert snapshot.json()[0]["editable"] is True
    assert snapshot.json()[0]["reconciliation_status"] == "pending"
    assert snapshot.json()[0]["preview"]["request"]["ticker"] == "AAPL"
    assert amend_response.status_code == 200
    assert second_ib_app.placed_orders[-1][0] == 700


def test_unavailable_startup_keeps_restored_open_records_pending(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())

    second_ib_app = FakeIbOrderApp(connected=False)
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        snapshot = client.get("/orders")

    assert snapshot.status_code == 200
    assert snapshot.json()[0]["status"] == "submitted"
    assert snapshot.json()[0]["reconciliation_status"] == "pending"
    assert second_ib_app.open_order_requests == 0


def test_successful_open_order_snapshot_marks_unseen_active_orders_stale(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        second_ib_app.emit_open_order_end()
        snapshot = client.get("/orders")

    assert snapshot.status_code == 200
    assert snapshot.json()[0]["status"] == "stale"
    assert snapshot.json()[0]["reconciliation_status"] == "stale"
    assert snapshot.json()[0]["is_open"] is False
    assert snapshot.json()[0]["is_current_day_history"] is False


def test_startup_with_completed_empty_ib_snapshot_marks_persisted_open_orders_stale(
    tmp_path,
):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        second_ib_app.emit_open_order_end()
        second_ib_app.emit_execution_end(90_000)
        second_ib_app.emit_completed_orders_end()
        snapshot = client.get("/orders")

    order = snapshot.json()[0]
    assert order["status"] == "stale"
    assert order["reconciliation_status"] == "stale"
    assert order["is_open"] is False
    assert order["is_current_day_history"] is False
    assert second_ib_app.all_open_order_requests == 0
    assert second_ib_app.open_order_requests == 1
    assert second_ib_app.auto_open_order_requests == [True]
    assert second_ib_app.execution_requests[0][0] == 90_000
    assert second_ib_app.completed_order_requests == [False]


def test_confirmed_order_clears_stale_only_read_only_reason(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        second_ib_app.emit_open_order_end()
        second_ib_app.emit_status(700, "Submitted", remaining=10)
        snapshot = client.get("/orders")

    order = snapshot.json()[0]
    assert order["status"] == "working"
    assert order["reconciliation_status"] == "confirmed"
    assert order["editable"] is True
    assert order["read_only_reason"] is None


def test_confirmed_unsupported_open_order_replaces_stale_read_only_reason(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "STP"
    order.totalQuantity = 10
    order.auxPrice = 180
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(second_api) as client:
        second_ib_app.emit_open_order_end()
        second_ib_app.emit_status(
            700,
            "Submitted",
            account="DU1234567",
            remaining=10,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")

    order = snapshot.json()[0]
    assert order["status"] == "working"
    assert order["reconciliation_status"] == "confirmed"
    assert order["editable"] is False
    assert order["read_only_reason"] == (
        "Order details were not fully reconstructed from IB."
    )


def test_execution_reconciles_existing_order_by_perm_id_and_dedupes(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app, orders_database_path=database_path)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"

    with TestClient(api) as client:
        client.post("/orders/transmit", json=stock_order_payload())
        ib_app.emit_status(700, "Submitted", perm_id=12345)
        ib_app.emit_execution(
            contract=contract,
            execution_id="0001.abc",
            order_id=999,
            perm_id=12345,
            account="DU1234567",
            side="BOT",
            shares=10,
            price=191.5,
            avg_price=191.5,
            cumulative_quantity=10,
            execution_time="2026-06-27T02:30:00+00:00",
        )
        ib_app.emit_execution(
            contract=contract,
            execution_id="0001.abc",
            order_id=999,
            perm_id=12345,
            account="DU1234567",
            side="BOT",
            shares=10,
            price=191.5,
            avg_price=191.5,
            cumulative_quantity=10,
            execution_time="2026-06-27T02:30:00+00:00",
        )
        snapshot = client.get("/orders")

    order = snapshot.json()[0]
    assert order["order_id"] == 700
    assert order["status"] == "filled"
    assert order["filled"] == 10
    assert order["remaining"] == 0
    assert order["avg_fill_price"] == 191.5
    assert order["execution_id"] == "0001.abc"
    assert order["execution_ids"] == ["0001.abc"]
    assert order["execution_time"] == "2026-06-27T02:30:00+00:00"
    assert order["updated_at"] == "2026-06-27T02:30:00+00:00"


def test_execution_with_zero_order_id_uses_perm_id_durable_identity():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"

    with TestClient(api) as client:
        ib_app.emit_execution(
            contract=contract,
            execution_id="0002.def",
            order_id=0,
            perm_id=45678,
            account="DU1234567",
            side="SLD",
            shares=5,
            price=205.25,
            avg_price=205.25,
            cumulative_quantity=5,
            execution_time="2026-06-27T03:15:00+00:00",
        )
        snapshot = client.get("/orders")

    order = snapshot.json()[0]
    assert order["order_id"] == -45678
    assert order["perm_id"] == 45678
    assert order["status"] == "filled"
    assert order["preview"]["summary"] == "SELL 5 AAPL STK @ 205.25"
    assert order["display_details"] == [
        "Perm ID 45678",
        "Execution 0002.def",
        "API order -45678",
    ]
    assert order["execution_side"] == "SELL"
    assert order["execution_price"] == 205.25


def test_backend_marks_current_day_execution_for_history():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    executed_at = datetime.now(US_MARKET_TIME_ZONE).replace(microsecond=0).isoformat()

    with TestClient(api) as client:
        ib_app.emit_execution(
            contract=contract,
            execution_id="0003.ghi",
            order_id=0,
            perm_id=45679,
            account="DU1234567",
            side="BOT",
            shares=5,
            price=205.25,
            avg_price=205.25,
            cumulative_quantity=5,
            execution_time=executed_at,
        )
        snapshot = client.get("/orders")

    order = snapshot.json()[0]
    assert order["is_open"] is False
    assert order["is_current_day_history"] is True


def test_current_day_history_does_not_use_generic_updated_at():
    request = StockOrderRequest.model_validate(stock_order_payload())
    now = datetime.now(US_MARKET_TIME_ZONE).replace(microsecond=0).isoformat()
    record = OrderRecord(
        order_id=700,
        account=request.account,
        status="cancelled",
        editable=False,
        submitted_at=now,
        updated_at=now,
        preview=OrderService(None).preview(request),
    )

    assert record.is_current_day_history is False


def test_execution_end_marks_request_complete():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api):
        ib_app.emit_execution_end(90_000)

    assert 90_000 in api.state.order_service.completed_execution_req_ids


def test_completed_filled_order_reconciles_stale_record_by_perm_id(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())
        first_ib_app.emit_status(700, "Submitted", perm_id=12345)

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.orderId = 999
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 190.5
    order.tif = "GTC"
    order.permId = 12345
    order_state = type(
        "OrderState",
        (),
        {"completedStatus": "Filled", "completedTime": "20260627 10:30:00"},
    )()

    with TestClient(second_api) as client:
        second_ib_app.emit_open_order_end()
        second_ib_app.emit_completed_order(contract, order, order_state)
        snapshot = client.get("/orders")

    completed = snapshot.json()[0]
    assert completed["order_id"] == 700
    assert completed["status"] == "filled"
    assert completed["reconciliation_status"] == "confirmed"
    assert completed["filled"] == 10
    assert completed["remaining"] == 0
    assert completed["completed_time"] == "2026-06-27T10:30:00+00:00"
    assert completed["preview"]["request"]["ticker"] == "AAPL"


def test_completed_cancelled_order_creates_read_only_record():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.orderId = 801
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "STP"
    order.totalQuantity = 10
    order.auxPrice = 180
    order.tif = "DAY"
    order.permId = 98765
    order_state = type(
        "OrderState",
        (),
        {"completedStatus": "Cancelled", "completedTime": "20260627 11:00:00"},
    )()

    with TestClient(api) as client:
        ib_app.emit_completed_order(contract, order, order_state)
        snapshot = client.get("/orders")

    completed = snapshot.json()[0]
    assert completed["order_id"] == 801
    assert completed["status"] == "cancelled"
    assert completed["editable"] is False
    assert completed["read_only_reason"] == (
        "Completed order details were not fully reconstructed from IB."
    )
    assert completed["preview"]["summary"] == "BUY 10 AAPL STK STOP stop 180 DAY"
    assert completed["display_details"] == ["Perm ID 98765", "API order 801"]
    assert completed["completed_status"] == "Cancelled"


def test_backend_marks_current_day_completed_order_for_history():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    completed_at = datetime.now(US_MARKET_TIME_ZONE).strftime("%Y%m%d %H:%M:%S")
    order = Order()
    order.orderId = 802
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 180
    order.tif = "DAY"
    order.permId = 98766
    order_state = type(
        "OrderState",
        (),
        {"completedStatus": "Cancelled", "completedTime": completed_at},
    )()

    with TestClient(api) as client:
        ib_app.emit_completed_order(contract, order, order_state)
        snapshot = client.get("/orders")

    completed = snapshot.json()[0]
    assert completed["is_open"] is False
    assert completed["is_current_day_history"] is True


def test_completed_orders_end_marks_response_complete():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api):
        ib_app.emit_completed_orders_end()

    assert api.state.order_service.completed_orders_received is True


def test_order_store_restores_latest_ib_status_after_restart(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())
        first_ib_app.emit_status(
            700,
            "Filled",
            filled=10,
            remaining=0,
            avg_fill_price=191.5,
            perm_id=12345,
        )

    second_api = create_orders_test_app(
        FakeIbOrderApp(),
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        snapshot = client.get("/orders")

    assert snapshot.status_code == 200
    order = snapshot.json()[0]
    assert order["status"] == "filled"
    assert order["reconciliation_status"] == "confirmed"
    assert order["filled"] == 10
    assert order["remaining"] == 0
    assert order["avg_fill_price"] == 191.5
    assert order["perm_id"] == 12345


def test_order_status_reconciles_by_perm_id_after_restart(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())
        first_ib_app.emit_status(700, "Submitted", perm_id=12345)

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(second_api) as client:
        second_ib_app.emit_status(
            999,
            "Filled",
            filled=10,
            remaining=0,
            avg_fill_price=191.5,
            perm_id=12345,
        )
        snapshot = client.get("/orders")

    assert snapshot.status_code == 200
    orders = snapshot.json()
    assert [order["order_id"] for order in orders] == [700]
    assert orders[0]["status"] == "filled"
    assert orders[0]["avg_fill_price"] == 191.5


def test_open_order_rekeys_perm_id_match_after_restart(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())
        first_ib_app.emit_status(700, "Submitted", perm_id=12345)

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 190.5
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(second_api) as client:
        second_ib_app.emit_status(
            999,
            "Submitted",
            account="DU1234567",
            remaining=10,
            perm_id=12345,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        amend_response = client.patch(
            "/orders/999",
            json={"account": "DU1234567", "limit_price": 191.25},
        )
        snapshot = client.get("/orders")

    assert amend_response.status_code == 200
    assert [order["order_id"] for order in snapshot.json()] == [999]
    assert second_ib_app.placed_orders[-1][0] == 999


def test_open_order_reconciliation_keeps_persisted_perm_id_rows(tmp_path):
    database_path = tmp_path / "orders.sqlite3"
    first_ib_app = FakeIbOrderApp()
    first_api = create_orders_test_app(
        first_ib_app,
        orders_database_path=database_path,
    )

    with TestClient(first_api) as client:
        client.post("/orders/transmit", json=stock_order_payload())
        first_ib_app.emit_status(700, "Submitted", perm_id=60285899)

    store = OrderStore(database_path)
    stale = store.list_orders()[0]
    corrected_preview = stale.preview.model_copy(
        update={
            "account": "U6985190",
            "request": stale.preview.request.model_copy(
                update={"account": "U6985190"},
            ),
        },
    )
    store.upsert_order(
        stale.model_copy(
            update={
                "order_id": 0,
                "account": "U6985190",
                "preview": corrected_preview,
            },
        ),
    )

    second_ib_app = FakeIbOrderApp()
    second_api = create_orders_test_app(
        second_ib_app,
        orders_database_path=database_path,
    )
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "SPOT"
    order = Order()
    order.account = "U6985190"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 190.5
    order.tif = "GTC"
    order.clientId = 0
    order.permId = 60285899

    with TestClient(second_api) as client:
        second_ib_app.emit_status(
            -23,
            "Submitted",
            account="U6985190",
            remaining=10,
            perm_id=60285899,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")

    orders = snapshot.json()
    persisted = OrderStore(database_path).list_orders()
    assert len(persisted) == 2
    assert len(orders) == 2
    assert -23 in {record.order_id for record in persisted}
    current = next(order for order in orders if order["order_id"] == -23)
    assert current["account"] == "U6985190"
    assert current["preview"]["account"] == "U6985190"
    assert current["preview"]["request"]["account"] == "U6985190"


def test_transmit_requires_connected_ib_app():
    ib_app = FakeIbOrderApp(connected=False)
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=stock_order_payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "Interactive Brokers is not connected."}
    assert ib_app.placed_orders == []


def test_stock_order_requires_share_quantity():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **stock_order_payload(),
    }
    payload.pop("quantity")

    with TestClient(api) as client:
        response = client.post("/orders/preview", json=payload)

    assert response.status_code == 422
    assert "quantity" in response.text


def test_stock_order_rejects_fractional_share_quantity():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **stock_order_payload(),
        "quantity": 1.5,
    }

    with TestClient(api) as client:
        response = client.post("/orders/preview", json=payload)

    assert response.status_code == 422
    assert "quantity" in response.text


def test_order_websocket_streams_submission_and_ib_rejection():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        with client.websocket_connect("/orders/ws") as websocket:
            assert websocket.receive_json() == {
                "type": "snapshot",
                "orders": [],
                "order": None,
            }

            api.state.order_service.submit(
                StockOrderRequest.model_validate(stock_order_payload()),
            )

            submitted = websocket.receive_json()
            assert submitted["type"] == "update"
            assert submitted["order"]["status"] == "submitted"

            ib_app.emit_status(
                700,
                "Inactive",
                rejection_message="Account is not allowed to trade this contract.",
            )
            rejected = websocket.receive_json()

    assert rejected["order"]["status"] == "rejected"
    assert (
        rejected["order"]["rejection_message"]
        == "Account is not allowed to trade this contract."
    )


def test_order_subscriber_queue_drops_oldest_updates_for_slow_clients():
    ib_app = FakeIbOrderApp()
    service = OrderService(ib_app, subscriber_queue_size=2)
    subscriber = service.subscribe()
    subscriber.get_nowait()

    for _ in range(3):
        service.submit(StockOrderRequest.model_validate(stock_order_payload()))

    updates = [subscriber.get_nowait(), subscriber.get_nowait()]

    assert subscriber.empty()
    assert [update.order.order_id for update in updates if update.order] == [701, 702]


def test_cancel_order_calls_ib_and_streams_cancelled_status():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=stock_order_payload())
        order_id = submit_response.json()["order"]["order_id"]
        response = client.post(
            f"/orders/{order_id}/cancel",
            json={"account": "DU1234567"},
        )

    assert response.status_code == 200
    assert response.json()["order"]["status"] == "cancelled"
    assert ib_app.cancelled_orders == [(700, "")]


def test_cancel_and_amend_reject_account_mismatch():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=stock_order_payload())
        order_id = submit_response.json()["order"]["order_id"]
        cancel_response = client.post(
            f"/orders/{order_id}/cancel",
            json={"account": "DU7654321"},
        )
        amend_response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU7654321", "quantity": 12},
        )

    assert cancel_response.status_code == 400
    assert cancel_response.json() == {
        "detail": "Cancellation account does not match the submitted order.",
    }
    assert amend_response.status_code == 400
    assert amend_response.json() == {
        "detail": "Amendment account does not match the submitted order.",
    }
    assert ib_app.cancelled_orders == []
    assert [placed_order[0] for placed_order in ib_app.placed_orders] == [700]


def test_cancelled_order_ignores_late_ib_inactive_status():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = option_strategy_payload(legs=[option_leg_payload()])

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=payload)
        order_id = submit_response.json()["order"]["order_id"]
        cancel_response = client.post(
            f"/orders/{order_id}/cancel",
            json={"account": "DU1234567"},
        )
        ib_app.emit_status(order_id, "Inactive")
        snapshot_response = client.get("/orders")

    assert cancel_response.status_code == 200
    assert snapshot_response.json()[0]["status"] == "cancelled"


def test_amend_stock_limit_order_places_replacement_with_same_id():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=stock_order_payload())
        order_id = submit_response.json()["order"]["order_id"]
        response = client.patch(
            f"/orders/{order_id}",
            json={
                "account": "DU1234567",
                "limit_price": 191.25,
                "time_in_force": "DAY",
            },
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Updated order 700."
    assert response.json()["order"]["preview"]["request"]["limit_price"] == 191.25
    assert response.json()["order"]["preview"]["request"]["time_in_force"] == "DAY"
    order_id, contract, order = ib_app.placed_orders[-1]
    assert order_id == 700
    assert contract.symbol == "AAPL"
    assert order.lmtPrice == 191.25
    assert order.tif == "DAY"


def test_amend_stock_order_updates_quantity():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=stock_order_payload())
        order_id = submit_response.json()["order"]["order_id"]
        response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU1234567", "quantity": 12},
        )

    assert response.status_code == 200
    assert response.json()["order"]["preview"]["request"]["quantity"] == 12
    order_id, _, order = ib_app.placed_orders[-1]
    assert order_id == 700
    assert order.totalQuantity == 12


def test_amend_rejects_quantity_below_filled_amount():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=stock_order_payload())
        order_id = submit_response.json()["order"]["order_id"]
        ib_app.emit_status(order_id, "Submitted", filled=5, remaining=5)
        response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU1234567", "quantity": 4},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Quantity cannot be reduced below the already-filled quantity.",
    }


def test_amend_reconciled_unknown_order_is_rejected():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        ib_app.emit_status(
            777,
            "Submitted",
            account="DU1234567",
            remaining=1,
        )
        snapshot = client.get("/orders")
        response = client.patch(
            "/orders/777",
            json={
                "account": "DU1234567",
                "limit_price": 191.25,
                "time_in_force": "DAY",
            },
        )

    assert snapshot.status_code == 200
    assert snapshot.json()[0]["editable"] is False
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Order details were not fully reconstructed from IB.",
    }
    assert ib_app.placed_orders == []


def test_external_bound_stock_limit_order_is_reconstructed_and_editable():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 190.5
    order.tif = "GTC"
    order.clientId = 0
    order.permId = 12345

    with TestClient(api) as client:
        ib_app.emit_status(
            777,
            "Submitted",
            account="DU1234567",
            remaining=10,
            perm_id=12345,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")
        response = client.patch(
            "/orders/777",
            json={"account": "DU1234567", "limit_price": 191.25},
        )

    external_order = snapshot.json()[0]
    assert external_order["editable"] is True
    assert external_order["perm_id"] == 12345
    assert external_order["preview"]["request"]["ticker"] == "AAPL"
    assert external_order["preview"]["request"]["quantity"] == 10
    assert external_order["preview"]["request"]["limit_price"] == 190.5
    assert response.status_code == 200
    assert ib_app.placed_orders[-1][0] == 777
    assert ib_app.placed_orders[-1][2].lmtPrice == 191.25


def test_manual_bound_negative_order_id_is_reconstructed_and_editable():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 190.5
    order.tif = "GTC"
    order.clientId = 0
    order.permId = 12345

    with TestClient(api) as client:
        ib_app.emit_status(
            -23,
            "Submitted",
            account="DU1234567",
            remaining=10,
            perm_id=12345,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")
        amend_response = client.patch(
            "/orders/-23",
            json={"account": "DU1234567", "limit_price": 191.25},
        )
        cancel_response = client.post(
            "/orders/-23/cancel",
            json={"account": "DU1234567"},
        )

    manual_order = snapshot.json()[0]
    assert manual_order["order_id"] == -23
    assert manual_order["display_details"] == ["Perm ID 12345", "API order -23"]
    assert manual_order["editable"] is True
    assert manual_order["read_only_reason"] is None
    assert cancel_response.status_code == 200
    assert amend_response.status_code == 200
    assert ib_app.cancelled_orders == [(-23, "")]
    assert ib_app.placed_orders[-1][0] == -23


def test_api_order_id_zero_stays_read_only_even_when_reconstructed():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 10
    order.lmtPrice = 190.5
    order.tif = "GTC"
    order.clientId = 0
    order.permId = 12345

    with TestClient(api) as client:
        ib_app.emit_status(
            0,
            "Submitted",
            account="DU1234567",
            remaining=10,
            perm_id=12345,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")
        amend_response = client.patch(
            "/orders/0",
            json={"account": "DU1234567", "limit_price": 191.25},
        )

    api_order = snapshot.json()[0]
    assert api_order["order_id"] == 0
    assert api_order["editable"] is False
    assert api_order["read_only_reason"] == (
        "Order 0 is visible but not bound for modification."
    )
    assert amend_response.status_code == 400


def test_external_bound_single_option_order_is_reconstructed_and_editable():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "OPT"
    contract.symbol = "AAPL"
    contract.lastTradeDateOrContractMonth = "20260619"
    contract.right = "C"
    contract.strike = 200
    contract.conId = 900001
    order = Order()
    order.account = "DU1234567"
    order.action = "SELL"
    order.orderType = "LMT"
    order.totalQuantity = 2
    order.lmtPrice = 1.25
    order.tif = "DAY"
    order.clientId = 0

    with TestClient(api) as client:
        ib_app.emit_status(
            779,
            "Submitted",
            account="DU1234567",
            remaining=2,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")
        response = client.patch(
            "/orders/779",
            json={"account": "DU1234567", "quantity": 3},
        )

    external_order = snapshot.json()[0]
    request = external_order["preview"]["request"]
    assert external_order["editable"] is True
    assert request["order_kind"] == "option_strategy"
    assert request["limit_price"] == -1.25
    assert request["legs"][0]["con_id"] == 900001
    assert request["legs"][0]["quantity"] == 2
    assert response.status_code == 200
    assert ib_app.placed_orders[-1][0] == 779
    assert ib_app.placed_orders[-1][2].totalQuantity == 3


def test_external_bound_combo_order_without_leg_details_can_amend_raw_order():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "BAG"
    contract.symbol = "AAPL"
    contract.comboLegs = [
        combo_leg(con_id=900001, action="BUY", ratio=1),
        combo_leg(con_id=900002, action="SELL", ratio=1),
    ]
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = 1.25
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(api) as client:
        ib_app.emit_status(
            780,
            "Submitted",
            account="DU1234567",
            remaining=1,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        wait_until(lambda: ib_app.contract_detail_requests)
        snapshot = client.get("/orders")
        response = client.patch(
            "/orders/780",
            json={"account": "DU1234567", "quantity": 2},
        )

    external_order = snapshot.json()[0]
    request = external_order["preview"]["request"]
    assert external_order["editable"] is True
    assert external_order["read_only_reason"] is None
    assert request["order_kind"] == "stock"
    assert request["order_type"] == "LIMIT"
    assert request["limit_price"] == 1.25
    assert response.status_code == 200
    placed_order_id, placed_contract, placed_order = ib_app.placed_orders[-1]
    assert placed_order_id == 780
    assert placed_contract.secType == "BAG"
    assert placed_order.totalQuantity == 2
    assert [request[1].conId for request in ib_app.contract_detail_requests] == [
        900001,
    ]
    assert [request[1].exchange for request in ib_app.contract_detail_requests] == [
        "SMART",
    ]
    assert [request[1].currency for request in ib_app.contract_detail_requests] == [
        "USD",
    ]


def test_external_bound_combo_order_with_resolved_leg_details_is_editable():
    ib_app = FakeIbOrderApp()
    ib_app.contract_details_by_con_id[900001] = option_contract(
        con_id=900001,
        strike=200,
    )
    ib_app.contract_details_by_con_id[900002] = option_contract(
        con_id=900002,
        strike=210,
    )
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "BAG"
    contract.symbol = "AAPL"
    contract.comboLegs = [
        combo_leg(con_id=900001, action="BUY", ratio=1),
        combo_leg(con_id=900002, action="SELL", ratio=1),
    ]
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = 1.25
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(api) as client:
        ib_app.emit_status(
            780,
            "Submitted",
            account="DU1234567",
            remaining=1,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        wait_until(lambda: api.state.order_service.snapshot()[0].editable)
        snapshot = client.get("/orders")
        response = client.patch(
            "/orders/780",
            json={"account": "DU1234567", "quantity": 2},
        )

    external_order = snapshot.json()[0]
    request = external_order["preview"]["request"]
    assert external_order["editable"] is True
    assert request["order_kind"] == "option_strategy"
    assert request["strategy_quantity"] == 1
    assert [leg["strike"] for leg in request["legs"]] == [200, 210]
    assert response.status_code == 200
    assert ib_app.placed_orders[-1][0] == 780


def test_external_bound_combo_order_accepts_negative_ib_limit_price():
    ib_app = FakeIbOrderApp()
    ib_app.contract_details_by_con_id[900001] = option_contract(
        con_id=900001,
        strike=200,
    )
    ib_app.contract_details_by_con_id[900002] = option_contract(
        con_id=900002,
        strike=210,
    )
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "BAG"
    contract.symbol = "AAPL"
    contract.comboLegs = [
        combo_leg(con_id=900001, action="BUY", ratio=1),
        combo_leg(con_id=900002, action="SELL", ratio=1),
    ]
    order = Order()
    order.account = "DU1234567"
    order.action = "SELL"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = -1.25
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(api) as client:
        ib_app.emit_status(
            781,
            "Submitted",
            account="DU1234567",
            remaining=1,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        wait_until(
            lambda: api.state.order_service.snapshot()[0].preview.request.order_kind
            == "option_strategy",
        )
        snapshot = client.get("/orders")

    request = snapshot.json()[0]["preview"]["request"]
    assert request["order_kind"] == "option_strategy"
    assert request["limit_price"] == -1.25


def test_external_bound_combo_order_uses_resolved_leg_local_symbols():
    ib_app = FakeIbOrderApp()
    first_leg = Contract()
    first_leg.conId = 900001
    first_leg.secType = "OPT"
    first_leg.localSymbol = "AMZN  260821C00110000"
    second_leg = Contract()
    second_leg.conId = 900002
    second_leg.secType = "OPT"
    second_leg.localSymbol = "AMZN  260821C00115000"
    ib_app.contract_details_by_con_id[900001] = first_leg
    ib_app.contract_details_by_con_id[900002] = second_leg
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "BAG"
    contract.symbol = "AMZN"
    contract.comboLegs = [
        combo_leg(con_id=900001, action="BUY", ratio=1),
        combo_leg(con_id=900002, action="SELL", ratio=1),
    ]
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = 1.25
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(api) as client:
        ib_app.emit_status(
            781,
            "Submitted",
            account="DU1234567",
            remaining=1,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        wait_until(lambda: api.state.order_service.snapshot()[0].editable)
        snapshot = client.get("/orders")

    request = snapshot.json()[0]["preview"]["request"]
    assert [leg["strike"] for leg in request["legs"]] == [110, 115]
    assert [leg["expiration"] for leg in request["legs"]] == ["20260821", "20260821"]


def test_external_bound_combo_order_uses_combo_leg_description_fallback():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "BAG"
    contract.symbol = "AMZN"
    contract.comboLegsDescrip = (
        "AMZN  260821C00110000,AMZN  260821C00115000"
    )
    contract.comboLegs = [
        combo_leg(con_id=0, action="BUY", ratio=1),
        combo_leg(con_id=0, action="SELL", ratio=1),
    ]
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = 1.25
    order.tif = "GTC"
    order.clientId = 0

    with TestClient(api) as client:
        ib_app.emit_status(
            782,
            "Submitted",
            account="DU1234567",
            remaining=1,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")

    order_record = snapshot.json()[0]
    assert order_record["editable"] is True
    request = order_record["preview"]["request"]
    assert [leg["strike"] for leg in request["legs"]] == [110, 115]


def test_external_unbound_or_unsupported_order_stays_read_only():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = "AAPL"
    order = Order()
    order.account = "DU1234567"
    order.action = "BUY"
    order.orderType = "STP"
    order.totalQuantity = 10
    order.auxPrice = 180
    order.tif = "GTC"
    order.clientId = 99

    with TestClient(api) as client:
        ib_app.emit_status(
            778,
            "Submitted",
            account="DU1234567",
            remaining=10,
            contract=contract,
            order=order,
            order_state=type("OrderState", (), {"status": "Submitted"})(),
        )
        snapshot = client.get("/orders")
        response = client.patch(
            "/orders/778",
            json={"account": "DU1234567", "limit_price": 191.25},
        )

    external_order = snapshot.json()[0]
    assert external_order["editable"] is False
    assert external_order["read_only_reason"] == (
        "Order details were not fully reconstructed from IB."
    )
    assert external_order["preview"]["summary"] == "BUY 10 AAPL STK STOP stop 180 GTC"
    assert external_order["display_details"] == ["API order 778"]
    assert response.status_code == 400
    assert ib_app.placed_orders == []


def test_failed_group_amendment_leaves_persisted_order_preview_unchanged():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(legs=[option_leg_payload()]),
        "take_profit_price": 2.5,
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=payload)
        order_id = submit_response.json()["order"]["order_id"]
        ib_app.rejected_order_type = "STP"
        response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU1234567", "quantity": 3},
        )
        snapshot = client.get("/orders")

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Interactive Brokers rejected part of this order amendment: "
            "combo stop orders are not supported"
        ),
    }
    parent = next(order for order in snapshot.json() if order["order_id"] == order_id)
    assert parent["preview"]["request"]["legs"][0]["quantity"] == 1


def test_amend_rejects_completed_orders():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=stock_order_payload())
        order_id = submit_response.json()["order"]["order_id"]
        ib_app.emit_status(order_id, "Filled", filled=10, remaining=0)
        response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU1234567", "limit_price": 191.25},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Order 700 cannot be amended from filled status.",
    }


def test_amend_option_strategy_updates_permitted_prices():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(legs=[option_leg_payload()]),
        "take_profit_price": 2.5,
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=payload)
        order_id = submit_response.json()["order"]["order_id"]
        response = client.patch(
            f"/orders/{order_id}",
            json={
                "account": "DU1234567",
                "limit_price": 1.35,
                "take_profit_price": 2.75,
                "stop_loss_price": 0.8,
                "time_in_force": "GTC",
            },
        )

    assert response.status_code == 200
    request = response.json()["order"]["preview"]["request"]
    assert request["limit_price"] == 1.35
    assert request["take_profit_price"] == 2.75
    assert request["stop_loss_price"] == 0.8
    assert request["time_in_force"] == "GTC"
    amended = ib_app.placed_orders[-3:]
    assert [order_id for order_id, _, _ in amended] == [700, 701, 702]
    assert amended[0][2].lmtPrice == 1.35
    assert amended[1][2].lmtPrice == 2.75
    assert amended[2][2].auxPrice == 0.8


def test_amend_option_bracket_quantity_updates_linked_exits():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(legs=[option_leg_payload()]),
        "take_profit_price": 2.5,
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=payload)
        order_id = submit_response.json()["order"]["order_id"]
        response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU1234567", "quantity": 3},
        )

    assert response.status_code == 200
    assert response.json()["order"]["preview"]["request"]["legs"][0]["quantity"] == 3
    amended = ib_app.placed_orders[-3:]
    assert [order_id for order_id, _, _ in amended] == [700, 701, 702]
    assert [order.totalQuantity for _, _, order in amended] == [3, 3, 3]
    assert amended[1][2].parentId == 700
    assert amended[2][2].parentId == 700


def test_amend_combo_strategy_quantity_preserves_leg_ratios():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = option_strategy_payload(
        legs=[
            option_leg_payload(strike=200, action="BUY"),
            option_leg_payload(strike=210, action="SELL"),
        ],
    )

    with TestClient(api) as client:
        submit_response = client.post("/orders/transmit", json=payload)
        order_id = submit_response.json()["order"]["order_id"]
        response = client.patch(
            f"/orders/{order_id}",
            json={"account": "DU1234567", "quantity": 2},
        )

    assert response.status_code == 200
    request = response.json()["order"]["preview"]["request"]
    assert request["strategy_quantity"] == 2
    assert [leg["quantity"] for leg in request["legs"]] == [1, 1]
    _, contract, order = ib_app.placed_orders[-1]
    assert order.totalQuantity == 2
    assert [leg.ratio for leg in contract.comboLegs] == [1, 1]


def test_option_strategy_preview_supports_multi_leg_request():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        "order_kind": "option_strategy",
        "account": "DU1234567",
        "limit_price": 1.25,
        "time_in_force": "DAY",
        "legs": [
            {
                "ticker": "aapl",
                "expiration": "2026-06-19",
                "right": "CALL",
                "strike": 200,
                "action": "BUY",
                "quantity": 1,
            },
            {
                "ticker": "aapl",
                "expiration": "2026-06-19",
                "right": "CALL",
                "strike": 210,
                "action": "SELL",
                "quantity": 1,
            },
        ],
    }

    with TestClient(api) as client:
        response = client.post("/orders/preview", json=payload)

    assert response.status_code == 200
    assert response.json()["order_kind"] == "option_strategy"
    assert "BUY 1 AAPL 2026-06-19 200 CALL" in response.json()["summary"]


def test_option_strategy_preview_includes_enabled_brackets():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(legs=[option_leg_payload()]),
        "take_profit_price": 2.5,
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        response = client.post("/orders/preview", json=payload)

    assert response.status_code == 200
    assert response.json()["estimated_order_type"] == "LIMIT + BRACKET"
    assert "take profit 2.5" in response.json()["summary"]
    assert "stop loss 0.75" in response.json()["summary"]
    assert response.json()["request"]["take_profit_price"] == 2.5
    assert response.json()["request"]["stop_loss_price"] == 0.75


def test_transmit_single_leg_option_order_places_option_contract():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = option_strategy_payload(legs=[option_leg_payload()])

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=payload)

    assert response.status_code == 200
    order_id, contract, order = ib_app.placed_orders[0]
    assert order_id == 700
    assert contract.secType == "OPT"
    assert contract.symbol == "AAPL"
    assert contract.lastTradeDateOrContractMonth == "20260619"
    assert contract.right == "C"
    assert contract.strike == 200
    assert order.action == "BUY"
    assert order.totalQuantity == 1
    assert order.lmtPrice == 1.25


def test_transmit_single_leg_option_credit_uses_positive_ib_limit_price():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(
            legs=[option_leg_payload(action="SELL")],
        ),
        "limit_price": -1.25,
    }

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=payload)

    assert response.status_code == 200
    assert response.json()["order"]["preview"]["request"]["limit_price"] == -1.25
    _, contract, order = ib_app.placed_orders[0]
    assert contract.secType == "OPT"
    assert order.action == "SELL"
    assert order.totalQuantity == 1
    assert order.lmtPrice == 1.25


def test_transmit_single_leg_option_bracket_places_linked_exit_orders():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(legs=[option_leg_payload()]),
        "take_profit_price": 2.5,
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=payload)

    assert response.status_code == 200
    assert ib_app.registered_order_ids == [700, 701, 702]
    assert [placed_order[0] for placed_order in ib_app.placed_orders] == [
        700,
        701,
        702,
    ]
    parent = ib_app.placed_orders[0][2]
    take_profit = ib_app.placed_orders[1][2]
    stop_loss = ib_app.placed_orders[2][2]
    assert parent.transmit is False
    assert take_profit.parentId == 700
    assert take_profit.action == "SELL"
    assert take_profit.orderType == "LMT"
    assert take_profit.totalQuantity == 1
    assert take_profit.lmtPrice == 2.5
    assert take_profit.transmit is False
    assert take_profit.eTradeOnly is False
    assert take_profit.firmQuoteOnly is False
    assert stop_loss.parentId == 700
    assert stop_loss.action == "SELL"
    assert stop_loss.orderType == "STP"
    assert stop_loss.auxPrice == 0.75
    assert stop_loss.transmit is True
    assert stop_loss.eTradeOnly is False
    assert stop_loss.firmQuoteOnly is False
    assert take_profit.ocaGroup == stop_loss.ocaGroup


def test_transmit_multi_leg_option_strategy_places_bag_combo_order():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = option_strategy_payload(
        legs=[
            option_leg_payload(strike=200, action="BUY"),
            option_leg_payload(strike=210, action="SELL"),
        ],
    )

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=payload)

    assert response.status_code == 200
    _, contract, order = ib_app.placed_orders[0]
    assert contract.secType == "BAG"
    assert contract.symbol == "AAPL"
    assert [leg.conId for leg in contract.comboLegs] == [900_001, 900_002]
    assert [leg.action for leg in contract.comboLegs] == ["BUY", "SELL"]
    assert order.orderType == "LMT"
    assert order.action == "BUY"
    assert order.lmtPrice == 1.25
    assert [request[1].strike for request in ib_app.contract_detail_requests] == [
        200,
        210,
    ]


def test_transmit_multi_leg_option_bracket_uses_combo_net_exit_prices():
    ib_app = FakeIbOrderApp()
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(
            legs=[
                option_leg_payload(strike=200, action="BUY"),
                option_leg_payload(strike=210, action="SELL"),
            ],
        ),
        "take_profit_price": 2.5,
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=payload)

    assert response.status_code == 200
    assert len(ib_app.placed_orders) == 3
    _, contract, parent = ib_app.placed_orders[0]
    _, take_profit_contract, take_profit = ib_app.placed_orders[1]
    _, stop_loss_contract, stop_loss = ib_app.placed_orders[2]
    assert contract.secType == "BAG"
    assert take_profit_contract.secType == "BAG"
    assert stop_loss_contract.secType == "BAG"
    assert parent.action == "BUY"
    assert take_profit.action == "SELL"
    assert take_profit.totalQuantity == 1
    assert take_profit.lmtPrice == 2.5
    assert stop_loss.action == "SELL"
    assert stop_loss.totalQuantity == 1
    assert stop_loss.auxPrice == 0.75


def test_transmit_option_bracket_surfaces_ib_rejection():
    ib_app = FakeIbOrderApp()
    ib_app.rejected_order_type = "STP"
    api = create_orders_test_app(ib_app)
    payload = {
        **option_strategy_payload(legs=[option_leg_payload()]),
        "stop_loss_price": 0.75,
    }

    with TestClient(api) as client:
        response = client.post("/orders/transmit", json=payload)
        snapshot_response = client.get("/orders")

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Interactive Brokers rejected this order combination: "
            "combo stop orders are not supported"
        ),
    }
    assert snapshot_response.status_code == 200
    assert snapshot_response.json() == []


def option_strategy_payload(*, legs):
    return {
        "order_kind": "option_strategy",
        "account": "DU1234567",
        "limit_price": 1.25,
        "time_in_force": "DAY",
        "legs": legs,
    }


class DelayedContractDetailsIbApp(FakeIbOrderApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))

    def complete_next_contract_details(self, contract: Contract) -> None:
        req_id, _ = self.contract_detail_requests[0]
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": contract})(),
        ]
        self.contract_details_ready_by_req_id[req_id].set()


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for condition.")


def option_leg_payload(*, strike=200, action="BUY"):
    return {
        "ticker": "aapl",
        "expiration": "2026-06-19",
        "right": "CALL",
        "strike": strike,
        "action": action,
        "quantity": 1,
    }


def option_contract(*, con_id: int, strike: float):
    contract = Contract()
    contract.conId = con_id
    contract.secType = "OPT"
    contract.symbol = "AAPL"
    contract.lastTradeDateOrContractMonth = "20260619"
    contract.right = "C"
    contract.strike = strike
    return contract


def combo_leg(*, con_id: int, action: str, ratio: int):
    leg = ComboLeg()
    leg.conId = con_id
    leg.action = action
    leg.ratio = ratio
    leg.exchange = "SMART"
    return leg
