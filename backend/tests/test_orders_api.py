from fastapi.testclient import TestClient
from ibapi.execution import ExecutionFilter

from app.schemas import StockOrderRequest
from conftest import FakeIbOrderApp, FakePortfolioClient, make_api
from app.orders.service import OrderService


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


def create_orders_test_app(ib_app: FakeIbOrderApp):
    return make_api(FakePortfolioClient(connected=ib_app.connected, app=ib_app))


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

    assert ib_app.open_order_requests == 1
    assert len(ib_app.execution_requests) == 1
    req_id, execution_filter = ib_app.execution_requests[0]
    assert req_id == 90_000
    assert ib_app.next_execution_req_id == 90_001
    assert isinstance(execution_filter, ExecutionFilter)


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
        "detail": (
            "Order 777 was reconciled from IB without editable contract details "
            "and cannot be amended."
        ),
    }
    assert ib_app.placed_orders == []


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
    assert ib_app.placed_orders[-1][0] == 700
    assert ib_app.placed_orders[-1][2].lmtPrice == 1.35


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


def option_leg_payload(*, strike=200, action="BUY"):
    return {
        "ticker": "aapl",
        "expiration": "2026-06-19",
        "right": "CALL",
        "strike": strike,
        "action": action,
        "quantity": 1,
    }
