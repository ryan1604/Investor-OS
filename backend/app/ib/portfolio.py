import logging
import threading
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from ibapi.contract import Contract

from app.config import Settings
from app.ib.app import (
    ACCOUNT_SUMMARY_TAGS,
    LEDGER_TOTAL_CASH_BALANCE_TAG,
    IbPortfolioApp,
)
from app.ib.contracts import market_data_contract
from app.ib.market_data_lines import market_data_line_budget
from app.portfolio.domain import (
    build_account_summary,
    merge_portfolio_rows,
)
from app.schemas import (
    IbStatus,
    MarketDataLineUsage,
    PortfolioAccountSummary,
    PortfolioPosition,
)

logger = logging.getLogger(__name__)

LEDGER_EXCHANGE_RATE_TAG = "ExchangeRate"
EXCHANGE_RATE_FIELD = "exchange_rate"
LEDGER_ACCOUNT_SUMMARY_REQUESTS = (
    ("$LEDGER:SGD", "cash_total_sgd"),
    ("$LEDGER:USD", "cash_total_usd"),
    ("$LEDGER", "cash_total"),
)


@dataclass(frozen=True)
class AnalysisMarketData:
    """Raw quote and Greek values for Portfolio Analysis.

    `by_con_id` holds position quotes plus, for options, IB Greeks: IV as a
    fraction, per-share delta/gamma/vega/theta, and the underlying price.
    `underlyings` holds quotes for option underlyings whose stock is not held.
    `exchange_rates` maps account to currency to IB's ledger rate into base.
    """

    by_con_id: dict[int, dict[str, float]]
    underlyings: dict[str, dict[str, float]]
    exchange_rates: dict[str, dict[str, float]] = field(default_factory=dict)


class PortfolioClient(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def get_status(self) -> IbStatus:
        ...

    def get_market_data_lines(self) -> MarketDataLineUsage:
        ...

    def get_positions(self) -> list[PortfolioPosition]:
        ...

    def get_account_summaries(
        self,
        positions: list[PortfolioPosition],
    ) -> list[PortfolioAccountSummary]:
        ...

    def refresh_account_summaries(self) -> None:
        ...

    def add_quote_viewer(self) -> None:
        ...

    def remove_quote_viewer(self) -> None:
        ...

    def add_analysis_viewer(self) -> None:
        ...

    def remove_analysis_viewer(self) -> None:
        ...

    def get_analysis_market_data(self) -> AnalysisMarketData:
        ...


class IbPortfolioClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app = IbPortfolioApp(
            market_data_line_capacity=(
                settings.max_market_data_lines - settings.market_data_line_reserve
            ),
        )
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.positions_request_lock = threading.Lock()
        self.positions_subscribed = False
        self.market_data_lock = threading.Lock()
        self.quote_viewers = 0
        self.analysis_viewers = 0
        # Underlying lines wait for the budget separately from position quotes.
        self.underlying_line_owner = object()
        self.option_underlyings: set[str] = set()

    def start(self) -> None:
        with self.lock:
            if self.app.isConnected():
                return

            self.app.connected_ready.clear()

            try:
                self.app.connect(
                    self.settings.ib_host,
                    self.settings.ib_port,
                    self.settings.ib_client_id,
                )
            except OSError:
                logger.exception("Could not connect to Interactive Brokers")
                return

            self.thread = threading.Thread(target=self.app.run, daemon=True)
            self.thread.start()
            self.app.connected_ready.wait(timeout=5)
            if self.app.isConnected():
                self.app.reqMarketDataType(3)
                self.app.reqAutoOpenOrders(True)

    def stop(self) -> None:
        if self.app.isConnected():
            with self.app.lock:
                req_ids = [
                    *self.app.market_req_to_con_id,
                    *self.app.underlying_req_to_symbol,
                ]
                pnl_req_ids = list(self.app.pnl_req_to_position_key)
                account_pnl_req_ids = list(self.app.account_pnl_req_to_account)

            for req_id in req_ids:
                self.app.cancelMktData(req_id)

            for req_id in pnl_req_ids:
                self.app.cancelPnLSingle(req_id)

            for req_id in account_pnl_req_ids:
                self.app.cancelPnL(req_id)

            if self.positions_subscribed:
                self.app.cancelPositions()

            self.app.disconnect()

    def get_status(self) -> IbStatus:
        return IbStatus(
            connected=self.app.isConnected(),
            host=self.settings.ib_host,
            port=self.settings.ib_port,
            client_id=self.settings.ib_client_id,
        )

    def get_market_data_lines(self) -> MarketDataLineUsage:
        snapshot = market_data_line_budget(self.app).snapshot()
        return MarketDataLineUsage(
            capacity=snapshot.capacity,
            used=snapshot.used,
            used_by_group=snapshot.used_by_group,
            pending_by_group=snapshot.pending_by_group,
        )

    def get_positions(self) -> list[PortfolioPosition]:
        if not self.app.isConnected():
            return []

        started_at = perf_counter()
        positions_started_at = perf_counter()
        self._ensure_positions_subscription()

        with self.app.lock:
            raw_positions = list(self.app.positions.values())

        positions_ms = elapsed_ms(positions_started_at)
        contracts_started_at = perf_counter()
        with self.market_data_lock:
            self._register_market_contracts(raw_positions)
            contracts_ms = elapsed_ms(contracts_started_at)
            market_data_started_at = perf_counter()
            self.option_underlyings = unheld_option_underlyings(raw_positions)
            if self.quote_viewers or self.analysis_viewers:
                self._subscribe_market_data()
            if self.analysis_viewers:
                self._sync_underlying_market_data()
        market_data_ms = elapsed_ms(market_data_started_at)
        pnl_started_at = perf_counter()
        self._subscribe_pnl(raw_positions)
        pnl_ms = elapsed_ms(pnl_started_at)
        merge_started_at = perf_counter()
        positions = self._merge_market_data(raw_positions)

        logger.info(
            "Portfolio positions refreshed positions=%s positions_ms=%.1f "
            "contracts_ms=%.1f market_data_ms=%.1f position_pnl_ms=%.1f "
            "merge_ms=%.1f total_ms=%.1f",
            len(positions),
            positions_ms,
            contracts_ms,
            market_data_ms,
            pnl_ms,
            elapsed_ms(merge_started_at),
            elapsed_ms(started_at),
        )

        return positions

    def _ensure_positions_subscription(self) -> None:
        with self.positions_request_lock:
            if self.positions_subscribed:
                return

            with self.app.lock:
                self.app.positions.clear()
                self.app.positions_ready.clear()

            self.app.reqPositions()
            self.app.positions_ready.wait(timeout=8)
            self.positions_subscribed = True

    def get_account_summaries(
        self,
        positions: list[PortfolioPosition],
    ) -> list[PortfolioAccountSummary]:
        started_at = perf_counter()
        with self.app.lock:
            summary_accounts = {
                account for account, _, _ in self.app.account_summary_values
            }

        accounts = sorted(
            summary_accounts | {position.account for position in positions}
        )
        pnl_started_at = perf_counter()
        self._subscribe_account_pnl(accounts)
        pnl_ms = elapsed_ms(pnl_started_at)
        summaries_started_at = perf_counter()
        summaries = [self._get_account_summary(account) for account in accounts]

        logger.info(
            "Portfolio account summaries assembled accounts=%s "
            "account_pnl_ms=%.1f assemble_ms=%.1f total_ms=%.1f",
            len(summaries),
            pnl_ms,
            elapsed_ms(summaries_started_at),
            elapsed_ms(started_at),
        )

        return summaries

    def refresh_account_summaries(self) -> None:
        if not self.app.isConnected():
            return

        started_at = perf_counter()
        self._refresh_account_summary_feed(ACCOUNT_SUMMARY_TAGS)
        for ledger_tag, field_name in LEDGER_ACCOUNT_SUMMARY_REQUESTS:
            self._refresh_account_summary_feed(
                ledger_tag,
                preserve_existing=True,
                tag_aliases={
                    LEDGER_TOTAL_CASH_BALANCE_TAG: field_name,
                    LEDGER_EXCHANGE_RATE_TAG: EXCHANGE_RATE_FIELD,
                },
            )

        logger.info(
            "Portfolio account summary feed refreshed total_ms=%.1f",
            elapsed_ms(started_at),
        )

    def _refresh_account_summary_feed(
        self,
        tags: str,
        *,
        preserve_existing: bool = False,
        tag_aliases: dict[str, str] | None = None,
    ) -> None:
        with self.app.lock:
            req_id = self.app.next_account_summary_req_id
            self.app.next_account_summary_req_id += 1
            initial_values = (
                self.app.account_summary_values.copy()
                if preserve_existing
                else None
            )

        ready, superseded_req_id = self.app.start_account_summary_request(
            req_id,
            initial_values=initial_values,
            tag_aliases=tag_aliases,
        )
        if superseded_req_id is not None:
            self.app.cancelAccountSummary(superseded_req_id)
        self.app.reqAccountSummary(req_id, "All", tags)
        ready.wait(timeout=8)
        self.app.abandon_account_summary_request(req_id)
        self.app.cancelAccountSummary(req_id)

    def _register_market_contracts(self, positions: list[PortfolioPosition]) -> None:
        active_con_ids = {
            position.con_id for position in positions if position.con_id is not None
        }

        stale_req_ids = []
        with self.app.lock:
            stale_con_ids = [
                con_id
                for con_id in self.app.market_contracts
                if con_id not in active_con_ids
            ]

            for con_id in stale_con_ids:
                self.app.market_contracts.pop(con_id, None)
                self.app.market_data.pop(con_id, None)
                req_id = self.app.market_req_ids.pop(con_id, None)

                if req_id is not None:
                    self.app.market_req_to_con_id.pop(req_id, None)
                    stale_req_ids.append(req_id)

            for position in positions:
                if position.con_id is None:
                    continue

                contract = Contract()
                contract.conId = position.con_id
                contract.symbol = position.symbol
                contract.secType = position.sec_type
                contract.lastTradeDateOrContractMonth = position.expiry or ""
                contract.strike = position.strike or 0
                contract.right = position.right or ""
                contract.multiplier = position.multiplier or ""
                contract.exchange = position.exchange or "SMART"
                contract.currency = position.currency
                contract.localSymbol = position.local_symbol or ""
                self.app.market_contracts[position.con_id] = market_data_contract(
                    contract,
                )

        for req_id in stale_req_ids:
            self.app.cancelMktData(req_id)
        market_data_line_budget(self.app).release("portfolio", len(stale_req_ids))

    def add_quote_viewer(self) -> None:
        with self.market_data_lock:
            self.quote_viewers += 1
            if self.quote_viewers == 1 and self.app.isConnected():
                self._subscribe_market_data()

    def remove_quote_viewer(self) -> None:
        with self.market_data_lock:
            self.quote_viewers = max(0, self.quote_viewers - 1)
            if not self.quote_viewers and not self.analysis_viewers:
                self._release_position_quotes()

    def add_analysis_viewer(self) -> None:
        with self.market_data_lock:
            self.analysis_viewers += 1
            if self.analysis_viewers == 1 and self.app.isConnected():
                self._subscribe_market_data()
                self._sync_underlying_market_data()

    def remove_analysis_viewer(self) -> None:
        with self.market_data_lock:
            self.analysis_viewers = max(0, self.analysis_viewers - 1)
            if self.analysis_viewers:
                return

            self._release_underlying_quotes(None)
            if not self.quote_viewers:
                self._release_position_quotes()

    def get_analysis_market_data(self) -> AnalysisMarketData:
        with self.app.lock:
            return AnalysisMarketData(
                by_con_id={
                    con_id: values.copy()
                    for con_id, values in self.app.market_data.items()
                },
                underlyings={
                    symbol: values.copy()
                    for symbol, values in self.app.underlying_market_data.items()
                },
                exchange_rates=exchange_rates(self.app.account_summary_values),
            )

    def _release_position_quotes(self) -> None:
        market_data_line_budget(self.app).clear_pending(self)
        with self.app.lock:
            req_ids = list(self.app.market_req_to_con_id)
            self.app.market_req_ids.clear()
            self.app.market_req_to_con_id.clear()
            self.app.market_data.clear()

        if self.app.isConnected():
            for req_id in req_ids:
                self.app.cancelMktData(req_id)
        market_data_line_budget(self.app).release("portfolio", len(req_ids))
        logger.info(
            "Portfolio position quotes paused cancelled_lines=%s",
            len(req_ids),
        )

    def _sync_underlying_market_data(self) -> None:
        """Quote option underlyings that are not held, and drop ones no longer needed."""
        with self.app.lock:
            subscribed = set(self.app.underlying_req_ids)
        self._release_underlying_quotes(subscribed - self.option_underlyings)

        missing = sorted(self.option_underlyings - subscribed)
        granted = market_data_line_budget(self.app).try_acquire(
            "portfolio",
            len(missing),
            owner=self.underlying_line_owner,
        )
        if granted < len(missing):
            logger.info(
                "Portfolio underlying quotes waiting for market-data lines "
                "subscribed=%s waiting=%s",
                granted,
                len(missing) - granted,
            )

        requests = []
        with self.app.lock:
            for symbol in missing[:granted]:
                req_id = self.app.next_market_req_id
                self.app.next_market_req_id += 1
                self.app.underlying_req_ids[symbol] = req_id
                self.app.underlying_req_to_symbol[req_id] = symbol
                requests.append((req_id, underlying_stock_contract(symbol)))

        for req_id, contract in requests:
            self.app.reqMktData(req_id, contract, "", False, False, [])

    def _release_underlying_quotes(self, symbols: set[str] | None) -> None:
        """Cancel underlying quotes for symbols, or all of them when symbols is None."""
        budget = market_data_line_budget(self.app)
        if symbols is None:
            budget.clear_pending(self.underlying_line_owner)
        with self.app.lock:
            if symbols is None:
                symbols = set(self.app.underlying_req_ids)
            req_ids = []
            for symbol in symbols:
                req_id = self.app.underlying_req_ids.pop(symbol, None)
                self.app.underlying_market_data.pop(symbol, None)
                if req_id is not None:
                    self.app.underlying_req_to_symbol.pop(req_id, None)
                    req_ids.append(req_id)

        if self.app.isConnected():
            for req_id in req_ids:
                self.app.cancelMktData(req_id)
        budget.release("portfolio", len(req_ids))

    def _subscribe_market_data(self) -> None:
        requests = []
        with self.app.lock:
            missing_contracts = [
                contract
                for con_id, contract in self.app.market_contracts.items()
                if con_id not in self.app.market_req_ids
            ]
        granted = market_data_line_budget(self.app).try_acquire(
            "portfolio",
            len(missing_contracts),
            owner=self,
        )
        contracts = missing_contracts[:granted]
        if len(contracts) < len(missing_contracts):
            logger.info(
                "Portfolio position quotes waiting for market-data lines "
                "subscribed=%s waiting=%s",
                len(contracts),
                len(missing_contracts) - len(contracts),
            )
        with self.app.lock:
            for contract in contracts:
                req_id = self.app.next_market_req_id
                self.app.next_market_req_id += 1
                self.app.market_req_ids[contract.conId] = req_id
                self.app.market_req_to_con_id[req_id] = contract.conId

                requests.append((req_id, contract))

        for req_id, contract in requests:
            self.app.reqMktData(req_id, contract, "", False, False, [])

    def _subscribe_pnl(self, positions: list[PortfolioPosition]) -> None:
        active_position_keys = {
            (position.account, position.con_id)
            for position in positions
            if position.con_id is not None
        }

        stale_req_ids = []
        requests = []
        with self.app.lock:
            stale_position_keys = [
                position_key
                for position_key in self.app.pnl_req_ids
                if position_key not in active_position_keys
            ]

            for position_key in stale_position_keys:
                req_id = self.app.pnl_req_ids.pop(position_key)
                self.app.pnl_req_to_position_key.pop(req_id, None)
                self.app.pnl_data.pop(position_key, None)
                stale_req_ids.append(req_id)

            for account, con_id in active_position_keys:
                position_key = (account, con_id)
                if position_key in self.app.pnl_req_ids:
                    continue

                req_id = self.app.next_pnl_req_id
                self.app.next_pnl_req_id += 1
                self.app.pnl_req_ids[position_key] = req_id
                self.app.pnl_req_to_position_key[req_id] = position_key
                requests.append((req_id, account, con_id))

        for req_id in stale_req_ids:
            self.app.cancelPnLSingle(req_id)

        for req_id, account, con_id in requests:
            self.app.reqPnLSingle(req_id, account, "", con_id)

    def _subscribe_account_pnl(self, accounts: list[str]) -> None:
        active_accounts = set(accounts)

        stale_req_ids = []
        requests = []
        with self.app.lock:
            stale_accounts = [
                account
                for account in self.app.account_pnl_req_ids
                if account not in active_accounts
            ]

            for account in stale_accounts:
                req_id = self.app.account_pnl_req_ids.pop(account)
                self.app.account_pnl_req_to_account.pop(req_id, None)
                self.app.account_pnl_data.pop(account, None)
                stale_req_ids.append(req_id)

            for account in active_accounts:
                if account in self.app.account_pnl_req_ids:
                    continue

                req_id = self.app.next_account_pnl_req_id
                self.app.next_account_pnl_req_id += 1
                self.app.account_pnl_req_ids[account] = req_id
                self.app.account_pnl_req_to_account[req_id] = account
                requests.append((req_id, account))

        for req_id in stale_req_ids:
            self.app.cancelPnL(req_id)

        for req_id, account in requests:
            self.app.reqPnL(req_id, account, "")

    def _merge_market_data(
        self,
        positions: list[PortfolioPosition],
    ) -> list[PortfolioPosition]:
        with self.app.lock:
            market_data = {
                con_id: values.copy()
                for con_id, values in self.app.market_data.items()
            }
            pnl_data = {
                position_key: values.copy()
                for position_key, values in self.app.pnl_data.items()
            }

        return merge_portfolio_rows(positions, market_data, pnl_data)

    def _get_account_summary(
        self,
        account: str,
    ) -> PortfolioAccountSummary:
        with self.app.lock:
            account_summary_values = self.app.account_summary_values.copy()
            account_pnl_data = {
                account: values.copy()
                for account, values in self.app.account_pnl_data.items()
            }

        return build_account_summary(
            account,
            account_summary_values,
            account_pnl_data,
        )


def exchange_rates(
    account_summary_values: dict[tuple[str, str, str], float],
) -> dict[str, dict[str, float]]:
    rates: dict[str, dict[str, float]] = {}
    for (account, tag, currency), value in account_summary_values.items():
        if tag == EXCHANGE_RATE_FIELD and value > 0:
            rates.setdefault(account, {})[currency] = value
    return rates


def unheld_option_underlyings(positions: list[PortfolioPosition]) -> set[str]:
    held_stocks = {
        position.symbol for position in positions if position.sec_type == "STK"
    }
    return {
        position.symbol
        for position in positions
        if position.sec_type == "OPT" and position.symbol not in held_stocks
    }


def underlying_stock_contract(symbol: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1_000


