from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
import logging
from threading import Event, Lock
from time import perf_counter

from ibapi.contract import Contract

from app.ib.app import IB_INVALID_CONTRACT_CODES, US_MARKET_TIME_ZONE, IbPortfolioApp
from app.ib.contracts import (
    us_equity_contract,
    us_option_contract,
    us_option_universe_contract,
)
from app.options.client import (
    OptionsDataUnavailable,
    ScannerContractSelection,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.options.domain import OptionMetadata, to_option_quote
from app.options.store import CompletedDailyBar
from app.tickers import normalize_ticker
from app.schemas import OptionQuote

OPTION_MARKET_DATA_GENERIC_TICKS = "100,101,104,106"
OPTION_RIGHTS = ("C", "P")
logger = logging.getLogger(__name__)


def raise_invalid_ticker_if_needed(app, req_id: int, ticker: str) -> None:
    request_errors = getattr(app, "request_errors_by_req_id", None)
    if request_errors is None:
        return

    with app.lock:
        request_error = request_errors.pop(req_id, None)

    if request_error and request_error[0] in IB_INVALID_CONTRACT_CODES:
        raise OptionsDataUnavailable(f"Invalid ticker: {ticker}.")


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
        ready.wait(timeout=self.timeout_seconds)

        with self.app.lock:
            bars = list(self.app.historical_bars.pop(req_id, []))
            self.app.historical_req_tickers.pop(req_id, None)
            self.app.historical_data_ready_by_req_id.pop(req_id, None)

        raise_invalid_ticker_if_needed(self.app, req_id, normalized_ticker)
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

        self.app.reqMarketDataType(3)
        self.app.reqMktData(
            chart_market_req_id,
            contract,
            "",
            False,
            False,
            [],
        )
        try:
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
            self.app.cancelMktData(chart_market_req_id)
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
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    app.reqContractDetails(req_id, us_equity_contract(ticker))
    completed = ready.wait(timeout=timeout_seconds)

    with app.lock:
        contract_details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)

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


class IbOptionMetadataProvider:
    def __init__(self, app: IbPortfolioApp, *, timeout_seconds: int = 8) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    def fetch_expirations(self, ticker: str) -> list[str]:
        metadata = self.fetch_option_metadata(ticker)
        return metadata.expirations

    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        if not self.app.isConnected():
            raise OptionsDataUnavailable(
                "Options metadata is unavailable while IB is disconnected."
            )

        normalized_ticker = normalize_ticker(ticker)
        contract = us_equity_contract(normalized_ticker)

        with self.app.lock:
            contract_req_id = self.app.next_contract_details_req_id
            self.app.next_contract_details_req_id += 1
            self.app.contract_details[contract_req_id] = []
            contract_details_ready = Event()
            self.app.contract_details_ready_by_req_id[contract_req_id] = (
                contract_details_ready
            )

        self.app.reqContractDetails(contract_req_id, contract)
        contract_details_completed = contract_details_ready.wait(
            timeout=self.timeout_seconds
        )

        with self.app.lock:
            contract_details = self.app.contract_details.pop(contract_req_id, [])
            self.app.contract_details_ready_by_req_id.pop(contract_req_id, None)

        raise_invalid_ticker_if_needed(
            self.app,
            contract_req_id,
            normalized_ticker,
        )
        if not contract_details_completed:
            raise OptionsDataUnavailable(
                f"Options metadata request timed out for {normalized_ticker}."
            )
        if not contract_details:
            return OptionMetadata(expirations=[], strikes=[])

        underlying_con_id = contract_details[0].contract.conId
        with self.app.lock:
            option_req_id = self.app.next_option_params_req_id
            self.app.next_option_params_req_id += 1
            self.app.option_metadata[option_req_id] = OptionMetadata(
                expirations=[],
                strikes=[],
            )
            option_metadata_ready = Event()
            self.app.option_metadata_ready_by_req_id[option_req_id] = (
                option_metadata_ready
            )

        self.app.reqSecDefOptParams(
            option_req_id,
            normalized_ticker,
            "",
            "STK",
            underlying_con_id,
        )
        option_metadata_completed = option_metadata_ready.wait(
            timeout=self.timeout_seconds
        )

        with self.app.lock:
            metadata = self.app.option_metadata.pop(
                option_req_id,
                OptionMetadata(expirations=[], strikes=[]),
            )
            self.app.option_metadata_ready_by_req_id.pop(option_req_id, None)

        raise_invalid_ticker_if_needed(
            self.app,
            option_req_id,
            normalized_ticker,
        )
        if not option_metadata_completed:
            raise OptionsDataUnavailable(
                f"Options metadata request timed out for {normalized_ticker}."
            )
        return metadata


class IbOptionChainSnapshotProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        timeout_seconds: float = 4,
    ) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    def fetch_chain_quotes(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> dict[tuple[float, str], OptionQuote]:
        if not self.app.isConnected() or not strikes:
            return {}

        normalized_ticker = normalize_ticker(ticker)
        subscriptions = OptionMarketDataSubscriptions(
            self.app,
            normalized_ticker,
            expiration,
            strikes,
            snapshot=False,
        )

        try:
            subscriptions.open()
            Event().wait(self.timeout_seconds)
            raw_quotes = subscriptions.snapshot_values()
        finally:
            subscriptions.close()

        return {
            key: to_option_quote(
                values,
                strike=key[0],
                right=key[1],
            )
            for key, values in raw_quotes.items()
        }


class IbOptionChainStreamProvider:
    def __init__(self, app: IbPortfolioApp, *, wait_seconds: float = 1) -> None:
        self.app = app
        self.wait_seconds = wait_seconds

    def stream_chain_quotes(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: Event,
    ) -> Iterable[tuple[tuple[float, str], OptionQuote]]:
        if not self.app.isConnected() or not strikes:
            return

        normalized_ticker = normalize_ticker(ticker)
        latest_values: dict[tuple[float, str], dict[str, float | int | None]] = {}
        subscriptions = OptionMarketDataSubscriptions(
            self.app,
            normalized_ticker,
            expiration,
            strikes,
            snapshot=False,
        )

        try:
            subscriptions.open()

            while not stop_event.is_set():
                if not self.app.option_market_data_ready.wait(self.wait_seconds):
                    continue

                updates_started_at = perf_counter()
                changed_quotes: list[tuple[tuple[float, str], OptionQuote]] = []
                for key, current_values in subscriptions.changed_values(
                    latest_values
                ):
                    latest_values[key] = current_values
                    changed_quotes.append(
                        (
                            key,
                            to_option_quote(
                                current_values,
                                strike=key[0],
                                right=key[1],
                            )
                        )
                    )

                yield from changed_quotes
                logger.info(
                    "Option chain stream updates ticker=%s expiration=%s "
                    "changed_quotes=%s update_ms=%.1f",
                    normalized_ticker,
                    expiration,
                    len(changed_quotes),
                    elapsed_ms(updates_started_at),
                )
        finally:
            subscriptions.close()


class IbOptionScannerProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        contract_timeout_seconds: float = 8,
        quote_wait_seconds: float = 4,
        quote_batch_size: int = 40,
    ) -> None:
        self.app = app
        self.contract_timeout_seconds = contract_timeout_seconds
        self.quote_wait_seconds = quote_wait_seconds
        self.quote_batch_size = max(1, quote_batch_size)
        self.active_req_ids: set[int] = set()
        self.active_req_ids_lock = Lock()

    def fetch_option_contracts(
        self,
        ticker: str,
        expirations: list[str],
        strikes: list[float],
        right: str,
        cancel_event: Event,
    ) -> ScannerContractSelection:
        if not self.app.isConnected():
            raise OptionsDataUnavailable(
                "Options scanning is unavailable while IB is disconnected."
            )

        normalized_ticker = normalize_ticker(ticker)
        allowed_strikes = set(strikes)
        contracts: list[ScannerOptionContract] = []
        excluded_contracts = 0
        for expiration in expirations:
            if cancel_event.is_set():
                break
            selection = self._fetch_expiration_contracts(
                normalized_ticker,
                expiration,
                allowed_strikes,
                right,
            )
            contracts.extend(selection.contracts)
            excluded_contracts += selection.excluded_contracts
        return ScannerContractSelection(
            contracts=contracts,
            excluded_contracts=excluded_contracts,
        )

    def fetch_quotes(
        self,
        contracts: list[ScannerOptionContract],
        cancel_event: Event,
    ) -> list[ScannerOptionQuote]:
        quotes: list[ScannerOptionQuote] = []
        for start in range(0, len(contracts), self.quote_batch_size):
            if cancel_event.is_set():
                break
            quotes.extend(
                self._fetch_quote_batch(
                    contracts[start : start + self.quote_batch_size],
                    cancel_event,
                )
            )
        return quotes

    def refresh_quote(
        self,
        *,
        ticker: str,
        expiration: str,
        strike: float,
        right: str,
        con_id: int | None,
        local_symbol: str | None,
    ) -> ScannerOptionQuote:
        if not self.app.isConnected():
            raise OptionsDataUnavailable(
                "Option quote refresh is unavailable while IB is disconnected."
            )

        normalized_ticker = normalize_ticker(ticker)
        contracts = self._resolve_option_contracts(
            normalized_ticker,
            expiration,
            strike,
            right,
        )
        selected = select_refreshed_contract(
            contracts,
            con_id=con_id,
            local_symbol=local_symbol,
        )
        if selected is None:
            raise OptionsDataUnavailable(
                "The selected option contract can no longer be resolved."
            )

        quotes = self._fetch_quote_batch([selected], Event())
        if not quotes:
            raise OptionsDataUnavailable(
                "The selected option contract could not be quoted."
            )
        return quotes[0]

    def cancel(self) -> None:
        with self.active_req_ids_lock:
            req_ids = list(self.active_req_ids)
        for req_id in req_ids:
            self.app.cancelMktData(req_id)

    def _fetch_expiration_contracts(
        self,
        ticker: str,
        expiration: str,
        allowed_strikes: set[float],
        right: str,
    ) -> ScannerContractSelection:
        with self.app.lock:
            req_id = self.app.next_contract_details_req_id
            self.app.next_contract_details_req_id += 1
            self.app.contract_details[req_id] = []
            ready = Event()
            self.app.contract_details_ready_by_req_id[req_id] = ready

        self.app.reqContractDetails(
            req_id,
            us_option_universe_contract(
                ticker,
                expiration=expiration,
                right=right,
            ),
        )
        completed = ready.wait(timeout=self.contract_timeout_seconds)
        with self.app.lock:
            details = self.app.contract_details.pop(req_id, [])
            self.app.contract_details_ready_by_req_id.pop(req_id, None)

        raise_invalid_ticker_if_needed(self.app, req_id, ticker)
        if not completed:
            raise OptionsDataUnavailable(
                f"Option contract request timed out for {ticker} {expiration}."
            )

        contracts = [
            scanner_contract(detail.contract)
            for detail in details
            if is_standard_option_contract(
                detail.contract,
                ticker=ticker,
                expiration=expiration,
                allowed_strikes=allowed_strikes,
                right=right,
            )
        ]
        return ScannerContractSelection(
            contracts=contracts,
            excluded_contracts=len(details) - len(contracts),
        )

    def _resolve_option_contracts(
        self,
        ticker: str,
        expiration: str,
        strike: float,
        right: str,
    ) -> list[ScannerOptionContract]:
        with self.app.lock:
            req_id = self.app.next_contract_details_req_id
            self.app.next_contract_details_req_id += 1
            self.app.contract_details[req_id] = []
            ready = Event()
            self.app.contract_details_ready_by_req_id[req_id] = ready

        self.app.reqContractDetails(
            req_id,
            us_option_contract(
                ticker,
                expiration=expiration,
                strike=strike,
                right=right,
            ),
        )
        completed = ready.wait(timeout=self.contract_timeout_seconds)
        with self.app.lock:
            details = self.app.contract_details.pop(req_id, [])
            self.app.contract_details_ready_by_req_id.pop(req_id, None)

        raise_invalid_ticker_if_needed(self.app, req_id, ticker)
        if not completed:
            raise OptionsDataUnavailable(
                f"Option contract request timed out for {ticker} {expiration}."
            )

        return [
            scanner_contract(detail.contract)
            for detail in details
            if is_exact_standard_option_contract(
                detail.contract,
                ticker=ticker,
                expiration=expiration,
                strike=strike,
                right=right,
            )
        ]

    def _fetch_quote_batch(
        self,
        contracts: list[ScannerOptionContract],
        cancel_event: Event,
    ) -> list[ScannerOptionQuote]:
        req_ids: dict[int, ScannerOptionContract] = {}
        requests = []
        with self.app.lock:
            self.app.option_market_data_ready.clear()
            for contract in contracts:
                req_id = self.app.next_option_market_req_id
                self.app.next_option_market_req_id += 1
                self.app.option_market_req_to_key[req_id] = contract.con_id
                self.app.option_market_data[req_id] = {}
                req_ids[req_id] = contract
                requests.append(
                    (
                        req_id,
                        scanner_market_data_contract(contract),
                        OPTION_MARKET_DATA_GENERIC_TICKS,
                        False,
                        False,
                        [],
                    )
                )

        with self.active_req_ids_lock:
            self.active_req_ids.update(req_ids)
        try:
            self.app.reqMarketDataType(3)
            for request in requests:
                self.app.reqMktData(*request)
            cancel_event.wait(self.quote_wait_seconds)
            with self.app.lock:
                values_by_req_id = {
                    req_id: self.app.option_market_data.get(req_id, {}).copy()
                    for req_id in req_ids
                }
            return [
                ScannerOptionQuote(
                    contract=contract,
                    bid=clean_quote_value(values_by_req_id[req_id].get("bid")),
                    ask=clean_quote_value(values_by_req_id[req_id].get("ask")),
                    delta=clean_quote_value(values_by_req_id[req_id].get("delta")),
                )
                for req_id, contract in req_ids.items()
            ]
        finally:
            for req_id in req_ids:
                self.app.cancelMktData(req_id)
            with self.app.lock:
                for req_id in req_ids:
                    self.app.option_market_req_to_key.pop(req_id, None)
                    self.app.option_market_data.pop(req_id, None)
            with self.active_req_ids_lock:
                self.active_req_ids.difference_update(req_ids)


def is_standard_option_contract(
    contract: Contract,
    *,
    ticker: str,
    expiration: str,
    allowed_strikes: set[float],
    right: str,
) -> bool:
    return (
        contract.secType == "OPT"
        and contract.symbol == ticker
        and contract.currency == "USD"
        and contract.right in {right, "PUT" if right == "P" else "CALL"}
        and contract.multiplier == "100"
        and contract.lastTradeDateOrContractMonth[:8]
        == expiration.replace("-", "")
        and contract.strike in allowed_strikes
        and contract.strike > 0
        and contract.tradingClass == ticker
        and contract.conId > 0
        and bool(contract.localSymbol)
    )


def is_exact_standard_option_contract(
    contract: Contract,
    *,
    ticker: str,
    expiration: str,
    strike: float,
    right: str,
) -> bool:
    return (
        contract.secType == "OPT"
        and contract.symbol == ticker
        and contract.currency == "USD"
        and contract.right in {right, "PUT" if right == "P" else "CALL"}
        and contract.multiplier == "100"
        and contract.lastTradeDateOrContractMonth[:8]
        == expiration.replace("-", "")
        and contract.strike == strike
        and contract.tradingClass == ticker
        and contract.conId > 0
        and bool(contract.localSymbol)
    )


def select_refreshed_contract(
    contracts: list[ScannerOptionContract],
    *,
    con_id: int | None,
    local_symbol: str | None,
) -> ScannerOptionContract | None:
    if con_id is not None:
        matched_con_id = next(
            (contract for contract in contracts if contract.con_id == con_id),
            None,
        )
        if matched_con_id is not None:
            return matched_con_id
    if local_symbol:
        matched_local_symbol = next(
            (
                contract
                for contract in contracts
                if contract.local_symbol == local_symbol
            ),
            None,
        )
        if matched_local_symbol is not None:
            return matched_local_symbol
    return min(
        contracts,
        key=lambda contract: (
            0 if contract.exchange == "SMART" else 1,
            contract.con_id,
        ),
        default=None,
    )


def scanner_contract(contract: Contract) -> ScannerOptionContract:
    return ScannerOptionContract(
        con_id=contract.conId,
        ticker=contract.symbol,
        expiration=(
            f"{contract.lastTradeDateOrContractMonth[:4]}-"
            f"{contract.lastTradeDateOrContractMonth[4:6]}-"
            f"{contract.lastTradeDateOrContractMonth[6:8]}"
        ),
        strike=contract.strike,
        right=contract.right,
        exchange=contract.exchange or "SMART",
        currency=contract.currency,
        multiplier=contract.multiplier,
        trading_class=contract.tradingClass,
        local_symbol=contract.localSymbol,
    )


def scanner_market_data_contract(contract: ScannerOptionContract) -> Contract:
    ib_contract = Contract()
    ib_contract.conId = contract.con_id
    ib_contract.symbol = contract.ticker
    ib_contract.secType = "OPT"
    ib_contract.exchange = "SMART"
    ib_contract.currency = contract.currency
    ib_contract.lastTradeDateOrContractMonth = contract.expiration.replace("-", "")
    ib_contract.strike = contract.strike
    ib_contract.right = contract.right
    ib_contract.multiplier = contract.multiplier
    ib_contract.tradingClass = contract.trading_class
    ib_contract.localSymbol = contract.local_symbol
    return ib_contract


def clean_quote_value(value: float | int | None) -> float | None:
    if value is None:
        return None
    next_value = float(value)
    if abs(next_value) > 1e100:
        return None
    return next_value


class OptionMarketDataSubscriptions:
    def __init__(
        self,
        app: IbPortfolioApp,
        ticker: str,
        expiration: str,
        strikes: list[float],
        *,
        snapshot: bool,
    ) -> None:
        self.app = app
        self.ticker = ticker
        self.expiration = expiration
        self.strikes = strikes
        self.snapshot = snapshot
        self.req_ids: list[int] = []

    def open(self) -> None:
        started_at = perf_counter()
        requests = []
        with self.app.lock:
            self.app.option_market_data_ready.clear()

            for strike in self.strikes:
                for right in OPTION_RIGHTS:
                    req_id = self.app.next_option_market_req_id
                    self.app.next_option_market_req_id += 1
                    option_key = (strike, right)
                    self.app.option_market_req_to_key[req_id] = option_key
                    self.app.option_market_data[req_id] = {}
                    self.req_ids.append(req_id)
                    requests.append(
                        (
                            req_id,
                            us_option_contract(
                                self.ticker,
                                expiration=self.expiration,
                                strike=strike,
                                right=right,
                            ),
                            OPTION_MARKET_DATA_GENERIC_TICKS,
                            self.snapshot,
                            False,
                            [],
                        )
                    )

        for request in requests:
            self.app.reqMktData(*request)

        logger.info(
            "Option chain market-data subscriptions opened ticker=%s "
            "expiration=%s strikes=%s subscriptions=%s open_ms=%.1f",
            self.ticker,
            self.expiration,
            len(self.strikes),
            len(requests),
            elapsed_ms(started_at),
        )

    def snapshot_values(self) -> dict[tuple[float, str], dict[str, float | int | None]]:
        with self.app.lock:
            return {
                self.app.option_market_req_to_key[req_id]: self.app.option_market_data[
                    req_id
                ].copy()
                for req_id in self.req_ids
                if req_id in self.app.option_market_req_to_key
                and req_id in self.app.option_market_data
            }

    def changed_values(
        self,
        latest_values: dict[tuple[float, str], dict[str, float | int | None]],
    ) -> Iterable[tuple[tuple[float, str], dict[str, float | int | None]]]:
        with self.app.lock:
            self.app.option_market_data_ready.clear()

            for req_id in self.req_ids:
                key = self.app.option_market_req_to_key.get(req_id)
                values = self.app.option_market_data.get(req_id)
                if key is None or values is None:
                    continue

                current_values = values.copy()
                if latest_values.get(key) == current_values:
                    continue

                yield key, current_values

    def close(self) -> None:
        started_at = perf_counter()
        with self.app.lock:
            req_ids_to_cancel = list(self.req_ids)
            for req_id in self.req_ids:
                option_key = self.app.option_market_req_to_key.pop(req_id, None)
                if option_key is not None:
                    self.app.option_market_data.pop(req_id, None)

        for req_id in req_ids_to_cancel:
            self.app.cancelMktData(req_id)

        logger.info(
            "Option chain market-data subscriptions closed ticker=%s "
            "expiration=%s subscriptions=%s request_errors=%s close_ms=%.1f",
            self.ticker,
            self.expiration,
            len(req_ids_to_cancel),
            self.request_error_count(req_ids_to_cancel),
            elapsed_ms(started_at),
        )

    def request_error_count(self, req_ids: list[int]) -> int:
        request_errors = getattr(self.app, "request_errors_by_req_id", None)
        if request_errors is None:
            return 0

        with self.app.lock:
            return sum(1 for req_id in req_ids if req_id in request_errors)


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1_000
