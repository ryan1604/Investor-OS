from __future__ import annotations


from collections.abc import Iterable
from datetime import date, datetime, timedelta
import logging
from threading import Event

from ibapi.contract import Contract

from app.ib.app import US_MARKET_TIME_ZONE, IbPortfolioApp
from app.ib.contract_lookup import (
    raise_invalid_ticker_if_needed,
    request_contract_details,
)
from app.ib.contracts import us_equity_contract
from app.ib.market_data_lines import market_data_line_budget
from app.options.store import CompletedDailyBar
from app.options.types import OptionsDataUnavailable
from app.tickers import normalize_ticker

logger = logging.getLogger(__name__)


class IbHistoricalDailyBarProvider:
    def __init__(self, app: IbPortfolioApp, *, timeout_seconds: int = 8) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        if not self.app.isConnected():
            return []

        normalized_ticker = normalize_ticker(ticker)
        contract = us_equity_contract(normalized_ticker)
        duration_days = (end_date - start_date).days + 1

        with self.app.lock:
            req_id = self.app.next_historical_req_id
            self.app.next_historical_req_id += 1
            self.app.historical_bars[req_id] = []
            self.app.historical_req_tickers[req_id] = normalized_ticker
            ready = Event()
            self.app.historical_data_ready_by_req_id[req_id] = ready

        self.app.reqHistoricalData(
            req_id,
            contract,
            f"{end_date:%Y%m%d} 23:59:59 US/Eastern",
            f"{duration_days} D",
            "1 day",
            "TRADES",
            1,
            1,
            False,
            [],
        )
        completed = ready.wait(timeout=self.timeout_seconds)

        with self.app.lock:
            bars = list(self.app.historical_bars.pop(req_id, []))
            self.app.historical_req_tickers.pop(req_id, None)
            self.app.historical_data_ready_by_req_id.pop(req_id, None)

        raise_invalid_ticker_if_needed(self.app, req_id, normalized_ticker)
        if not completed:
            # Callers see no bars either way; this tells an IB-side delay apart
            # from an IB error, which the error callback logs separately.
            logger.warning(
                "Historical daily bars timed out ticker=%s req_id=%s "
                "duration_days=%s timeout_s=%s bars=%s",
                normalized_ticker,
                req_id,
                duration_days,
                self.timeout_seconds,
                len(bars),
            )
        return bars


class IbHistoricalDailyBarStreamProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        timeout_seconds: float = 8,
        wait_seconds: float = 1,
    ) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds
        self.wait_seconds = wait_seconds

    def stream_daily_bar_updates(
        self,
        ticker: str,
        stop_event: Event,
    ) -> Iterable[CompletedDailyBar]:
        if not self.app.isConnected():
            return

        normalized_ticker = normalize_ticker(ticker)
        snapshot_provider = IbHistoricalDailyBarProvider(
            self.app,
            timeout_seconds=self.timeout_seconds,
        )
        snapshot_bars = snapshot_provider.fetch_daily_bars(
            normalized_ticker,
            *current_daily_snapshot_range(),
        )
        active_bar = max(
            snapshot_bars,
            key=lambda bar: bar.trading_date,
            default=None,
        )
        contract = resolve_direct_market_data_contract(
            self.app,
            normalized_ticker,
            timeout_seconds=self.timeout_seconds,
        )

        with self.app.lock:
            chart_market_req_id = self.app.next_chart_market_req_id
            self.app.next_chart_market_req_id += 1
            self.app.chart_market_req_tickers[chart_market_req_id] = normalized_ticker
            self.app.chart_market_updates_by_req_id[chart_market_req_id] = []
            chart_market_ready = Event()
            self.app.chart_market_ready_by_req_id[chart_market_req_id] = (
                chart_market_ready
            )

        budget = market_data_line_budget(self.app)
        chart_lines = budget.acquire("chart", 1, stop_event=stop_event)
        try:
            if not chart_lines:
                return
            self.app.reqMarketDataType(3)
            self.app.reqMktData(
                chart_market_req_id,
                contract,
                "",
                False,
                False,
                [],
            )
            if active_bar is not None:
                yield active_bar

            while not stop_event.is_set():
                if not chart_market_ready.wait(self.wait_seconds):
                    continue

                with self.app.lock:
                    updates = list(
                        self.app.chart_market_updates_by_req_id.get(
                            chart_market_req_id,
                            [],
                        )
                    )
                    self.app.chart_market_updates_by_req_id[chart_market_req_id] = []
                    chart_market_ready.clear()

                for bar in updates:
                    active_bar = merge_daily_bar(active_bar, bar)
                    yield active_bar
        finally:
            if chart_lines:
                self.app.cancelMktData(chart_market_req_id)
                budget.release("chart", chart_lines)
            with self.app.lock:
                self.app.chart_market_req_tickers.pop(chart_market_req_id, None)
                self.app.chart_market_updates_by_req_id.pop(
                    chart_market_req_id,
                    None,
                )
                self.app.chart_market_ready_by_req_id.pop(chart_market_req_id, None)


def resolve_direct_market_data_contract(
    app: IbPortfolioApp,
    ticker: str,
    *,
    timeout_seconds: float,
) -> Contract:
    req_id, contract_details, completed = request_contract_details(
        app,
        us_equity_contract(ticker),
        timeout_seconds=timeout_seconds,
        urgent=True,
    )

    raise_invalid_ticker_if_needed(app, req_id, ticker)
    if not completed:
        raise OptionsDataUnavailable(
            f"Market-data contract request timed out for {ticker}."
        )
    if not contract_details:
        raise OptionsDataUnavailable(
            f"Market-data contract is unavailable for {ticker}."
        )

    contract = contract_details[0].contract
    if not contract.primaryExchange:
        raise OptionsDataUnavailable(
            f"Primary market-data exchange is unavailable for {ticker}."
        )

    contract.exchange = contract.primaryExchange
    return contract


def current_daily_snapshot_range() -> tuple[date, date]:
    current_date = datetime.now(US_MARKET_TIME_ZONE).date()
    return current_date - timedelta(days=1), current_date


def merge_daily_bar(
    current_bar: CompletedDailyBar | None,
    next_bar: CompletedDailyBar,
) -> CompletedDailyBar:
    if current_bar is None or current_bar.trading_date != next_bar.trading_date:
        return next_bar

    return CompletedDailyBar(
        ticker=next_bar.ticker,
        trading_date=next_bar.trading_date,
        open=current_bar.open,
        high=max(current_bar.high, next_bar.high),
        low=min(current_bar.low, next_bar.low),
        close=next_bar.close,
        volume=current_bar.volume,
    )
