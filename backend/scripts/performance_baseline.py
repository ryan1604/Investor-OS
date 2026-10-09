from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.ib.market_data_lines import MarketDataLineBudget
from app.ib.pacing import OutstandingRequestLimiter
from app.main import AppOverrides, create_app
from app.schemas import (
    BollingerBandPoint,
    IbStatus,
    OptionChainLiveMessage,
    OptionChainResponse,
    OptionChainRow,
    OptionDailyBar,
    OptionExpiration,
    OptionExpirationsResponse,
    OptionQuote,
    OptionsAnalysisResponse,
    OptionsChartLiveMessage,
    PortfolioAccountSummary,
    PortfolioPosition,
    RsiPoint,
)
from app.timing import elapsed_ms


DEFAULT_ITERATIONS = 10
TICKER = "AAPL"
EXPIRATION = "2026-06-19"


@dataclass
class TimingRecorder:
    values: dict[str, list[float]] = field(default_factory=dict)

    def measure(self, name: str, callback: Callable[[], Any]) -> Any:
        started_at = time.perf_counter()
        result = callback()
        self.values.setdefault(name, []).append(elapsed_ms(started_at))
        return result

    def summary(self) -> dict[str, dict[str, float]]:
        return {
            name: summarize_samples(samples)
            for name, samples in sorted(self.values.items())
        }


class BaselinePortfolioClient:
    def __init__(self, recorder: TimingRecorder, position_count: int) -> None:
        self.recorder = recorder
        self.positions = make_positions(position_count)
        self.app = BaselineIbOrderApp()
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def get_status(self) -> IbStatus:
        return self.recorder.measure(
            "ib.status_wait_ms",
            lambda: IbStatus(
                connected=True,
                host="127.0.0.1",
                port=7497,
                client_id=1,
            ),
        )

    def get_positions(self) -> list[PortfolioPosition]:
        return self.recorder.measure(
            "ib.positions_wait_ms",
            lambda: [position.model_copy(deep=True) for position in self.positions],
        )

    def get_account_summaries(
        self,
        positions: list[PortfolioPosition],
    ) -> list[PortfolioAccountSummary]:
        def build_summary() -> list[PortfolioAccountSummary]:
            market_value = sum(position.market_value or 0 for position in positions)
            return [
                PortfolioAccountSummary(
                    account="DU1234567",
                    net_liquidation=250_000,
                    daily_pnl=1_250,
                    daily_pnl_percent=0.5,
                    unrealized_pnl=8_400,
                    market_value=market_value,
                    maintenance_margin=25_000,
                    excess_liquidity=225_000,
                    buying_power=900_000,
                    cash_total_sgd=25_000,
                    cash_total_usd=50_000,
                    cash_total=83_500,
                )
            ]

        return self.recorder.measure("ib.account_summary_wait_ms", build_summary)

    def refresh_account_summaries(self) -> None:
        self.recorder.measure("ib.account_summary_refresh_wait_ms", lambda: None)


class BaselineOptionsClient:
    def __init__(self, recorder: TimingRecorder, chain_rows: int) -> None:
        self.recorder = recorder
        self.chain_rows = make_option_chain_rows(chain_rows)
        self.chart_points = make_chart_points(260)

    def cancel_scanner(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        def build_analysis() -> OptionsAnalysisResponse:
            return OptionsAnalysisResponse(
                ticker=ticker.upper(),
                underlying_price=192.5,
                candles=[point[0] for point in self.chart_points],
                bollinger_bands=[point[1] for point in self.chart_points],
                rsi=[point[2] for point in self.chart_points],
                message=f"Loaded analysis data for {ticker.upper()}.",
            )

        return self.recorder.measure("ib.options_analysis_wait_ms", build_analysis)

    def get_expirations(self, ticker: str) -> OptionExpirationsResponse:
        return OptionExpirationsResponse(
            ticker=ticker.upper(),
            expirations=[
                OptionExpiration(date=EXPIRATION, days_to_expiration=14),
                OptionExpiration(date="2026-07-17", days_to_expiration=42),
            ],
            selected_expiration=EXPIRATION,
        )

    def get_underlying_price(self, ticker: str) -> float:
        return 192.5

    def get_chain(self, ticker: str, expiration: str) -> OptionChainResponse:
        def build_chain() -> OptionChainResponse:
            return OptionChainResponse(
                ticker=ticker.upper(),
                expiration=expiration,
                underlying_price=192.5,
                rows=[row.model_copy(deep=True) for row in self.chain_rows],
                message=f"Loaded {len(self.chain_rows)} strike(s).",
            )

        return self.recorder.measure("ib.option_chain_wait_ms", build_chain)

    def stream_chain(
        self,
        ticker: str,
        expiration: str,
        *,
        stop_event: threading.Event,
    ):
        yield OptionChainLiveMessage(
            type="snapshot",
            ticker=ticker.upper(),
            expiration=expiration,
            rows=self.chain_rows,
            message=f"Streaming {len(self.chain_rows)} strike(s).",
        )
        for row in self.chain_rows[:5]:
            if stop_event.is_set():
                return
            yield OptionChainLiveMessage(
                type="update",
                ticker=ticker.upper(),
                expiration=expiration,
                row=row,
            )

    def stream_chart(self, ticker: str, *, stop_event: threading.Event):
        for candle, band, rsi in self.chart_points[:5]:
            if stop_event.is_set():
                return
            yield OptionsChartLiveMessage(
                type="update",
                ticker=ticker.upper(),
                candle=candle,
                bollinger_band=band,
                rsi=rsi,
            )


class BaselineIbOrderApp:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.request_errors_by_req_id = {}
        self.limit_errors_by_req_id = {}
        self.market_data_lines = MarketDataLineBudget(1_000_000)
        self.contract_details_slots = OutstandingRequestLimiter(None)
        self.connected = True
        self.next_order_id = 700
        self.next_execution_req_id = 90_000
        self.next_contract_details_req_id = 70_000
        self.contract_details = {}
        self.contract_details_ready_by_req_id = {}
        self.open_order_requests = 0
        self.auto_open_order_requests = []
        self.completed_order_requests = []
        self.execution_requests = []
        self.placed_orders = []
        self.cancelled_orders = []
        self.registered_order_ids = []
        self.listeners = []

    def market_data_line_usage(self) -> tuple[int, int]:
        return self.market_data_lines.used(), self.market_data_lines.capacity

    def limit_error_count(self, req_ids) -> dict[int, int]:
        counts = {}
        with self.lock:
            for req_id in req_ids:
                code = self.limit_errors_by_req_id.get(req_id)
                if code is not None:
                    counts[code] = counts.get(code, 0) + 1
        return counts

    def isConnected(self) -> bool:
        return self.connected

    def placeOrder(self, order_id, contract, order) -> None:
        self.placed_orders.append((order_id, contract, order))

    def cancelOrder(self, order_id, manual_cancel_order_time="") -> None:
        self.cancelled_orders.append((order_id, manual_cancel_order_time))

    def add_order_status_listener(self, listener) -> None:
        self.listeners.append(listener)

    def add_execution_listener(self, listener) -> None:
        self.listeners.append(listener)

    def add_execution_end_listener(self, listener) -> None:
        self.listeners.append(listener)

    def add_completed_order_listener(self, listener) -> None:
        self.listeners.append(listener)

    def add_completed_orders_end_listener(self, listener) -> None:
        self.listeners.append(listener)

    def add_open_order_end_listener(self, listener) -> None:
        self.listeners.append(listener)

    def register_submitted_order(self, order_id: int) -> None:
        self.registered_order_ids.append(order_id)

    def reqAutoOpenOrders(self, auto_bind: bool) -> None:
        self.auto_open_order_requests.append(auto_bind)

    def reqCompletedOrders(self, api_only: bool) -> None:
        self.completed_order_requests.append(api_only)

    def reqOpenOrders(self) -> None:
        self.open_order_requests += 1

    def reqExecutions(self, req_id, execution_filter) -> None:
        self.execution_requests.append((req_id, execution_filter))

    def reqContractDetails(self, req_id, contract) -> None:
        contract.conId = 900_000 + req_id
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": contract})(),
        ]
        self.contract_details_slots.release(req_id)
        self.contract_details_ready_by_req_id[req_id].set()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run repeatable fake-provider backend performance baselines.",
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--positions", type=int, default=250)
    parser.add_argument("--chain-rows", type=int, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baseline = run_baseline(
        iterations=args.iterations,
        position_count=args.positions,
        chain_rows=args.chain_rows,
    )
    payload = json.dumps(baseline, indent=2, sort_keys=True)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


def run_baseline(
    *,
    iterations: int,
    position_count: int,
    chain_rows: int,
) -> dict[str, Any]:
    recorder = TimingRecorder()
    portfolio_client = BaselinePortfolioClient(recorder, position_count)
    options_client = BaselineOptionsClient(recorder, chain_rows)

    with tempfile.TemporaryDirectory(
        prefix="investor-os-baseline-",
        ignore_cleanup_errors=True,
    ) as directory:
        data_path = Path(directory)
        api = create_app(
            Settings(**{
                name: str(data_path / f"{name.removesuffix('_database_path')}.sqlite3")
                for name in Settings.model_fields
                if name.endswith("_database_path")
            }),
            AppOverrides(
                client=portfolio_client,
                options_client=options_client,
            ),
        )

        with TestClient(api) as client:
            time.sleep(0.05)
            return collect_metrics(
                client,
                api,
                recorder,
                iterations=iterations,
                position_count=position_count,
                chain_rows=chain_rows,
            )


def collect_metrics(
    client: TestClient,
    api,
    recorder: TimingRecorder,
    *,
    iterations: int,
    position_count: int,
    chain_rows: int,
) -> dict[str, Any]:
    endpoints = [
        ("portfolio", "GET", "/portfolio", None),
        ("options_analysis", "GET", f"/options/{TICKER}/analysis", None),
        (
            "option_chain",
            "GET",
            f"/options/{TICKER}/chain?expiration={EXPIRATION}",
            None,
        ),
        ("stock_analysis_read", "GET", f"/stock-analysis/{TICKER}", None),
        (
            "stock_analysis_write",
            "PUT",
            f"/stock-analysis/{TICKER}",
            stock_analysis_payload(),
        ),
        ("orders_snapshot", "GET", "/orders", None),
    ]

    http_results = {
        name: measure_http_endpoint(client, method, path, body, iterations)
        for name, method, path, body in endpoints
    }
    websocket_results = {
        "portfolio_ws": measure_portfolio_websocket(client),
        "option_chain_ws": measure_websocket_messages(
            client,
            f"/options/{TICKER}/chain/ws?expiration={EXPIRATION}",
            message_count=2,
        ),
        "options_chart_ws": measure_websocket_messages(
            client,
            f"/options/{TICKER}/chart/ws",
            message_count=5,
        ),
        "orders_ws": measure_websocket_messages(client, "/orders/ws", message_count=1),
    }
    refresh_service = api.state.portfolio_refresh_service

    return {
        "workload": {
            "iterations": iterations,
            "portfolio_positions": position_count,
            "option_chain_rows": chain_rows,
            "chart_points": 260,
            "concurrent_workers": 4,
            "live_ib_credentials_required": False,
        },
        "http": http_results,
        "concurrent_http": measure_concurrent_workloads(client, iterations),
        "websocket": websocket_results,
        "instrumentation": {
            **recorder.summary(),
            "portfolio_subscriber_count": len(refresh_service.subscribers),
            "portfolio_queue_depths": [
                queue.qsize() for queue in refresh_service.subscribers
            ],
        },
        "budgets": {
            "portfolio_p95_ms": 75,
            "option_chain_p95_ms": 125,
            "options_analysis_p95_ms": 125,
            "stock_analysis_write_p95_ms": 50,
            "websocket_message_p95_ms": 75,
            "concurrent_request_p95_ms": 250,
        },
    }


def measure_http_endpoint(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    iterations: int,
) -> dict[str, Any]:
    samples = []
    payload_sizes = []

    for _ in range(iterations):
        started_at = time.perf_counter()
        if method == "PUT":
            response = client.put(path, json=body)
        else:
            response = client.get(path)
        samples.append(elapsed_ms(started_at))
        response.raise_for_status()
        payload_sizes.append(len(response.content))

    return {
        **summarize_samples(samples),
        "payload_bytes": summarize_samples(payload_sizes),
    }


def measure_portfolio_websocket(client: TestClient) -> dict[str, Any]:
    with client.websocket_connect("/portfolio/ws") as websocket:
        started_at = time.perf_counter()
        payload = websocket.receive_json()
        latency_ms = elapsed_ms(started_at)

    return {
        **summarize_samples([latency_ms]),
        "payload_bytes": len(json.dumps(payload, separators=(",", ":"))),
        "subscriber_count_during_receive": 1,
    }


def measure_websocket_messages(
    client: TestClient,
    path: str,
    *,
    message_count: int,
) -> dict[str, Any]:
    samples = []
    payload_sizes = []

    with client.websocket_connect(path) as websocket:
        for _ in range(message_count):
            started_at = time.perf_counter()
            payload = websocket.receive_json()
            samples.append(elapsed_ms(started_at))
            payload_sizes.append(len(json.dumps(payload, separators=(",", ":"))))

    return {
        **summarize_samples(samples),
        "payload_bytes": summarize_samples(payload_sizes),
    }


def measure_concurrent_workloads(
    client: TestClient,
    iterations: int,
) -> dict[str, Any]:
    workloads = {
        "analysis": lambda: client.get(f"/options/{TICKER}/analysis"),
        "chain": lambda: client.get(
            f"/options/{TICKER}/chain?expiration={EXPIRATION}"
        ),
        "current_price": lambda: client.get(
            f"/stock-analysis/{TICKER}/current-price"
        ),
        "stock_analysis_read": lambda: client.get(f"/stock-analysis/{TICKER}"),
        "stock_analysis_write": lambda: client.put(
            f"/stock-analysis/{TICKER}",
            json=stock_analysis_payload(),
        ),
        "transmit": lambda: client.post("/orders/transmit", json=stock_order_payload()),
        "amend": lambda: transmit_then_amend(client),
    }

    return {
        name: measure_concurrent_requests(
            callback,
            requests=max(4, iterations),
            workers=4,
        )
        for name, callback in workloads.items()
    }


def measure_concurrent_requests(
    callback: Callable[[], Any],
    *,
    requests: int,
    workers: int,
) -> dict[str, Any]:
    samples = []
    status_counts: dict[str, int] = {}

    def run_request() -> tuple[float, int]:
        started_at = time.perf_counter()
        response = callback()
        return elapsed_ms(started_at), response.status_code

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_request) for _ in range(requests)]
        for future in as_completed(futures):
            sample, status_code = future.result()
            samples.append(sample)
            status_key = str(status_code)
            status_counts[status_key] = status_counts.get(status_key, 0) + 1

    return {
        **summarize_samples(samples),
        "workers": workers,
        "requests": requests,
        "status_counts": dict(sorted(status_counts.items())),
    }


def transmit_then_amend(client: TestClient):
    submit_response = client.post("/orders/transmit", json=stock_order_payload())
    if submit_response.status_code != 200:
        return submit_response

    order_id = submit_response.json()["order"]["order_id"]
    return client.patch(
        f"/orders/{order_id}",
        json={"account": "DU1234567", "limit_price": 191.25},
    )


def stock_order_payload() -> dict[str, Any]:
    return {
        "order_kind": "stock",
        "account": "DU1234567",
        "ticker": TICKER,
        "action": "BUY",
        "quantity": 10,
        "order_type": "LIMIT",
        "limit_price": 190.5,
        "time_in_force": "DAY",
    }


def make_positions(count: int) -> list[PortfolioPosition]:
    positions = []
    for index in range(count):
        is_option = index % 3 != 0
        symbol = ["AAPL", "MSFT", "NVDA", "TSLA", "HIMS"][index % 5]
        quantity = 100 if not is_option else (1 if index % 2 == 0 else -1)
        market_value = 10_000 + index * 17
        positions.append(
            PortfolioPosition(
                account="DU1234567",
                con_id=100_000 + index,
                symbol=symbol,
                sec_type="OPT" if is_option else "STK",
                local_symbol=(
                    f"{symbol}  260619C{180 + index % 60:08d}"
                    if is_option
                    else None
                ),
                expiry="20260619" if is_option else None,
                strike=180 + index % 60 if is_option else None,
                right="C" if is_option else None,
                multiplier="100" if is_option else None,
                exchange="SMART",
                currency="USD",
                quantity=quantity,
                average_cost=150 + index % 40,
                last_price=155 + index % 35,
                change_percent=(index % 9) - 4,
                pnl=(index % 21) * 11.5,
                pnl_percent=(index % 11) - 5,
                unrealized_pnl=(index % 17) * 8.25,
                unrealized_pnl_percent=(index % 13) - 6,
                market_value=market_value,
                cost_basis=market_value * 0.92,
                average_price=market_value / max(abs(quantity), 1),
                net_liquidity=250_000,
                net_liquidity_percent=market_value / 250_000 * 100,
            )
        )
    return positions


def make_option_chain_rows(count: int) -> list[OptionChainRow]:
    rows = []
    for index in range(count):
        strike = 130 + index * 2.5
        rows.append(
            OptionChainRow(
                strike=strike,
                call=make_quote(strike, index, "C"),
                put=make_quote(strike, index, "P"),
            )
        )
    return rows


def make_quote(strike: float, index: int, right: str) -> OptionQuote:
    mid = round(0.5 + (index % 25) * 0.18, 2)
    return OptionQuote(
        local_symbol=f"AAPL  260619{right}{int(strike * 1000):08d}",
        delta=round(0.1 + (index % 80) / 100, 2),
        bid=round(mid - 0.05, 2),
        bid_size=10 + index,
        ask=round(mid + 0.05, 2),
        ask_size=12 + index,
        mid=mid,
        last=mid,
        close=round(mid - 0.02, 2),
        model_price=round(mid + 0.01, 2),
        change_percent=round((index % 12) - 6, 2),
        volume=100 + index * 3,
        open_interest=1_000 + index * 7,
        gamma=round(0.01 + (index % 10) / 1_000, 4),
        theta=round(-0.01 - (index % 10) / 1_000, 4),
        implied_volatility_percent=round(35 + (index % 20) * 0.4, 2),
        breakeven=round(strike + mid if right == "C" else strike - mid, 2),
    )


def make_chart_points(
    count: int,
) -> list[tuple[OptionDailyBar, BollingerBandPoint, RsiPoint]]:
    points = []
    for index in range(count):
        day = index + 1
        date = f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}"
        close = 180 + (day % 50) * 0.8
        points.append(
            (
                OptionDailyBar(
                    date=date,
                    open=round(close - 0.7, 2),
                    high=round(close + 1.1, 2),
                    low=round(close - 1.4, 2),
                    close=round(close, 2),
                    volume=1_000_000 + index * 1_000,
                ),
                BollingerBandPoint(
                    date=date,
                    upper=round(close + 4, 2),
                    middle=round(close, 2),
                    lower=round(close - 4, 2),
                ),
                RsiPoint(date=date, value=round(45 + (index % 30) * 0.7, 2)),
            )
        )
    return points


def stock_analysis_payload() -> dict[str, Any]:
    years = [2026, 2027, 2028, 2029, 2030]
    return {
        "version": 1,
        "payload": {
            "firstForecastYear": years[0],
            "bull": {"revenue": [120, 145, 170, 198, 230], "margin": [0.22] * 5},
            "base": {"revenue": [110, 128, 148, 166, 185], "margin": [0.18] * 5},
            "bear": {"revenue": [98, 105, 112, 120, 130], "margin": [0.12] * 5},
        },
    }


def summarize_samples(samples: list[float] | list[int]) -> dict[str, float]:
    sorted_samples = sorted(float(sample) for sample in samples)
    if not sorted_samples:
        return {"min": 0, "mean": 0, "p50": 0, "p95": 0, "max": 0}
    return {
        "min": round(sorted_samples[0], 3),
        "mean": round(statistics.fmean(sorted_samples), 3),
        "p50": round(percentile(sorted_samples, 0.5), 3),
        "p95": round(percentile(sorted_samples, 0.95), 3),
        "p99": round(percentile(sorted_samples, 0.99), 3),
        "max": round(sorted_samples[-1], 3),
    }


def percentile(sorted_samples: list[float], fraction: float) -> float:
    index = min(len(sorted_samples) - 1, max(0, int(len(sorted_samples) * fraction)))
    return sorted_samples[index]


if __name__ == "__main__":
    main()
