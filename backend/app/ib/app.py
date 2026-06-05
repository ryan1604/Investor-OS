from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.wrapper import EWrapper

from app.ib.contracts import (
    clean_ib_float,
    clean_ib_int,
    clean_ib_price,
    format_ib_expiration,
    market_data_contract,
    parse_ib_bar_date,
)
from app.options.domain import OptionMetadata
from app.options.store import CompletedDailyBar
from app.portfolio.domain import percent
from app.schemas import PortfolioPosition

logger = logging.getLogger(__name__)

LAST_TICK_TYPES = {4, 68}
CLOSE_TICK_TYPES = {9, 75}
OPTION_BID_TICK_TYPES = {1, 66}
OPTION_ASK_TICK_TYPES = {2, 67}
OPTION_BID_SIZE_TICK_TYPES = {0, 69}
OPTION_ASK_SIZE_TICK_TYPES = {3, 70}
OPTION_VOLUME_TICK_TYPES = {8, 29, 30, 74}
IB_INFO_CODES = {2104, 2106, 2158}
IB_DEBUG_CODES = {2100}
IB_MARKET_DATA_SUBSCRIPTION_CODES = {10089, 10091, 10167}
IB_HISTORICAL_NO_DATA_CODES = {162}
IB_INVALID_CONTRACT_CODES = {200}
ACCOUNT_VALUE_KEYS = {
    "BuyingPower",
    "ExcessLiquidity",
    "GrossPositionValue",
    "MaintMarginReq",
    "NetLiquidation",
}
ACCOUNT_SUMMARY_TAGS = ",".join(sorted(ACCOUNT_VALUE_KEYS))
LEDGER_TOTAL_CASH_BALANCE_TAG = "TotalCashBalance"
US_MARKET_TIME_ZONE = ZoneInfo("America/New_York")


def completed_daily_bar(ticker: str, bar) -> CompletedDailyBar | None:
    trading_date = parse_ib_bar_date(str(bar.date))
    if trading_date is None:
        return None

    return CompletedDailyBar(
        ticker=ticker,
        trading_date=trading_date.isoformat(),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=clean_ib_int(bar.volume),
    )


@dataclass
class IbPortfolioState:
    positions: dict[tuple[str, int, str], PortfolioPosition] = field(
        default_factory=dict
    )
    market_data: dict[int, dict[str, float]] = field(default_factory=dict)
    market_contracts: dict[int, Contract] = field(default_factory=dict)
    market_req_ids: dict[int, int] = field(default_factory=dict)
    market_req_to_con_id: dict[int, int] = field(default_factory=dict)
    pnl_req_ids: dict[tuple[str, int], int] = field(default_factory=dict)
    pnl_req_to_position_key: dict[int, tuple[str, int]] = field(default_factory=dict)
    pnl_data: dict[tuple[str, int], dict[str, float | None]] = field(
        default_factory=dict
    )
    account_pnl_req_ids: dict[str, int] = field(default_factory=dict)
    account_pnl_req_to_account: dict[int, str] = field(default_factory=dict)
    account_pnl_data: dict[str, dict[str, float | None]] = field(
        default_factory=dict
    )
    next_market_req_id: int = 10_000
    next_pnl_req_id: int = 30_000
    next_account_pnl_req_id: int = 50_000


@dataclass
class IbAccountSummaryState:
    values: dict[tuple[str, str, str], float] = field(default_factory=dict)
    pending_values: dict[int, dict[tuple[str, str, str], float]] = field(
        default_factory=dict
    )
    ready_by_req_id: dict[int, threading.Event] = field(default_factory=dict)
    tag_aliases_by_req_id: dict[int, dict[str, str]] = field(default_factory=dict)
    active_req_id: int | None = None
    next_req_id: int = 40_000


@dataclass
class IbHistoricalState:
    bars: dict[int, list[CompletedDailyBar]] = field(default_factory=dict)
    req_tickers: dict[int, str] = field(default_factory=dict)
    ready_by_req_id: dict[int, threading.Event] = field(default_factory=dict)
    update_req_tickers: dict[int, str] = field(default_factory=dict)
    updates_by_req_id: dict[int, list[CompletedDailyBar]] = field(default_factory=dict)
    update_ready_by_req_id: dict[int, threading.Event] = field(default_factory=dict)
    chart_market_req_tickers: dict[int, str] = field(default_factory=dict)
    chart_market_updates_by_req_id: dict[int, list[CompletedDailyBar]] = field(
        default_factory=dict
    )
    chart_market_ready_by_req_id: dict[int, threading.Event] = field(
        default_factory=dict
    )
    contract_details: dict[int, list[ContractDetails]] = field(default_factory=dict)
    contract_details_ready_by_req_id: dict[int, threading.Event] = field(
        default_factory=dict
    )
    request_errors_by_req_id: dict[int, tuple[int, str]] = field(default_factory=dict)
    next_historical_req_id: int = 60_000
    next_chart_market_req_id: int = 110_000
    next_contract_details_req_id: int = 70_000


@dataclass
class IbOptionMarketState:
    metadata: dict[int, OptionMetadata] = field(default_factory=dict)
    metadata_ready_by_req_id: dict[int, threading.Event] = field(default_factory=dict)
    market_req_to_key: dict[int, tuple[float, str]] = field(default_factory=dict)
    market_data: dict[int, dict[str, float | int | None]] = field(
        default_factory=dict
    )
    next_params_req_id: int = 80_000
    next_market_req_id: int = 90_000


@dataclass
class IbOrderState:
    next_order_id: int | None = None
    next_execution_req_id: int = 90_000
    status_listeners: list[Callable[..., None]] = field(default_factory=list)
    submitted_order_ids: set[int] = field(default_factory=set)


class IbPortfolioApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.portfolio_state = IbPortfolioState()
        self.account_summary_state = IbAccountSummaryState()
        self.historical_state = IbHistoricalState()
        self.option_state = IbOptionMarketState()
        self.order_state = IbOrderState()
        self.positions = self.portfolio_state.positions
        self.account_summary_values = self.account_summary_state.values
        self.pending_account_summary_values = (
            self.account_summary_state.pending_values
        )
        self.account_summary_ready_by_req_id = (
            self.account_summary_state.ready_by_req_id
        )
        self.account_summary_tag_aliases_by_req_id = (
            self.account_summary_state.tag_aliases_by_req_id
        )
        self.market_data = self.portfolio_state.market_data
        self.market_contracts = self.portfolio_state.market_contracts
        self.market_req_ids = self.portfolio_state.market_req_ids
        self.market_req_to_con_id = self.portfolio_state.market_req_to_con_id
        self.pnl_req_ids = self.portfolio_state.pnl_req_ids
        self.pnl_req_to_position_key = self.portfolio_state.pnl_req_to_position_key
        self.pnl_data = self.portfolio_state.pnl_data
        self.account_pnl_req_ids = self.portfolio_state.account_pnl_req_ids
        self.account_pnl_req_to_account = (
            self.portfolio_state.account_pnl_req_to_account
        )
        self.account_pnl_data = self.portfolio_state.account_pnl_data
        self.request_errors_by_req_id = self.historical_state.request_errors_by_req_id
        self.historical_bars = self.historical_state.bars
        self.historical_req_tickers = self.historical_state.req_tickers
        self.historical_data_ready_by_req_id = self.historical_state.ready_by_req_id
        self.historical_update_req_tickers = (
            self.historical_state.update_req_tickers
        )
        self.historical_updates_by_req_id = self.historical_state.updates_by_req_id
        self.historical_update_ready_by_req_id = (
            self.historical_state.update_ready_by_req_id
        )
        self.chart_market_req_tickers = (
            self.historical_state.chart_market_req_tickers
        )
        self.chart_market_updates_by_req_id = (
            self.historical_state.chart_market_updates_by_req_id
        )
        self.chart_market_ready_by_req_id = (
            self.historical_state.chart_market_ready_by_req_id
        )
        self.contract_details = self.historical_state.contract_details
        self.contract_details_ready_by_req_id = (
            self.historical_state.contract_details_ready_by_req_id
        )
        self.option_metadata = self.option_state.metadata
        self.option_metadata_ready_by_req_id = (
            self.option_state.metadata_ready_by_req_id
        )
        self.option_market_req_to_key = self.option_state.market_req_to_key
        self.option_market_data = self.option_state.market_data
        self.order_status_listeners = self.order_state.status_listeners
        self.submitted_order_ids = self.order_state.submitted_order_ids
        self.logged_warnings: set[tuple[int, int]] = set()
        self.positions_ready = threading.Event()
        self.market_data_ready = threading.Event()
        self.pnl_ready = threading.Event()
        self.account_pnl_ready = threading.Event()
        self.option_market_data_ready = threading.Event()
        self.connected_ready = threading.Event()
        self.lock = threading.Lock()

    @property
    def active_account_summary_req_id(self) -> int | None:
        return self.account_summary_state.active_req_id

    @active_account_summary_req_id.setter
    def active_account_summary_req_id(self, value: int | None) -> None:
        self.account_summary_state.active_req_id = value

    @property
    def next_market_req_id(self) -> int:
        return self.portfolio_state.next_market_req_id

    @next_market_req_id.setter
    def next_market_req_id(self, value: int) -> None:
        self.portfolio_state.next_market_req_id = value

    @property
    def next_pnl_req_id(self) -> int:
        return self.portfolio_state.next_pnl_req_id

    @next_pnl_req_id.setter
    def next_pnl_req_id(self, value: int) -> None:
        self.portfolio_state.next_pnl_req_id = value

    @property
    def next_account_summary_req_id(self) -> int:
        return self.account_summary_state.next_req_id

    @next_account_summary_req_id.setter
    def next_account_summary_req_id(self, value: int) -> None:
        self.account_summary_state.next_req_id = value

    @property
    def next_account_pnl_req_id(self) -> int:
        return self.portfolio_state.next_account_pnl_req_id

    @next_account_pnl_req_id.setter
    def next_account_pnl_req_id(self, value: int) -> None:
        self.portfolio_state.next_account_pnl_req_id = value

    @property
    def next_order_id(self) -> int | None:
        return self.order_state.next_order_id

    @next_order_id.setter
    def next_order_id(self, value: int | None) -> None:
        self.order_state.next_order_id = value

    @property
    def next_execution_req_id(self) -> int:
        return self.order_state.next_execution_req_id

    @next_execution_req_id.setter
    def next_execution_req_id(self, value: int) -> None:
        self.order_state.next_execution_req_id = value

    @property
    def next_historical_req_id(self) -> int:
        return self.historical_state.next_historical_req_id

    @next_historical_req_id.setter
    def next_historical_req_id(self, value: int) -> None:
        self.historical_state.next_historical_req_id = value

    @property
    def next_chart_market_req_id(self) -> int:
        return self.historical_state.next_chart_market_req_id

    @next_chart_market_req_id.setter
    def next_chart_market_req_id(self, value: int) -> None:
        self.historical_state.next_chart_market_req_id = value

    @property
    def next_contract_details_req_id(self) -> int:
        return self.historical_state.next_contract_details_req_id

    @next_contract_details_req_id.setter
    def next_contract_details_req_id(self, value: int) -> None:
        self.historical_state.next_contract_details_req_id = value

    @property
    def next_option_params_req_id(self) -> int:
        return self.option_state.next_params_req_id

    @next_option_params_req_id.setter
    def next_option_params_req_id(self, value: int) -> None:
        self.option_state.next_params_req_id = value

    @property
    def next_option_market_req_id(self) -> int:
        return self.option_state.next_market_req_id

    @next_option_market_req_id.setter
    def next_option_market_req_id(self, value: int) -> None:
        self.option_state.next_market_req_id = value

    def nextValidId(self, orderId: int) -> None:
        with self.lock:
            self.next_order_id = orderId
        self.connected_ready.set()

    def add_order_status_listener(self, listener: Callable[..., None]) -> None:
        with self.lock:
            self.order_status_listeners.append(listener)

    def register_submitted_order(self, order_id: int) -> None:
        with self.lock:
            self.submitted_order_ids.add(order_id)

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        self._notify_order_status(
            orderId,
            status,
            filled=clean_ib_float(filled),
            remaining=clean_ib_float(remaining),
            avg_fill_price=clean_ib_price(avgFillPrice),
            perm_id=permId or None,
            parent_order_id=parentId or None,
        )

    def openOrder(self, orderId: int, contract: Contract, order, orderState) -> None:
        self._notify_order_status(
            orderId,
            getattr(orderState, "status", "") or "Submitted",
            filled=0,
            remaining=clean_ib_float(getattr(order, "totalQuantity", 0)),
            perm_id=getattr(order, "permId", 0) or None,
            parent_order_id=getattr(order, "parentId", 0) or None,
            account=getattr(order, "account", "") or None,
        )

    def execDetails(self, reqId: int, contract: Contract, execution) -> None:
        self._notify_order_status(
            getattr(execution, "orderId", 0),
            "Filled",
            filled=clean_ib_float(getattr(execution, "shares", None)),
            remaining=0,
            avg_fill_price=clean_ib_price(getattr(execution, "price", None)),
            perm_id=getattr(execution, "permId", 0) or None,
            account=getattr(execution, "acctNumber", "") or None,
        )

    def _notify_order_status(
        self,
        order_id: int,
        status: str,
        *,
        filled: float | None = None,
        remaining: float | None = None,
        avg_fill_price: float | None = None,
        perm_id: int | None = None,
        parent_order_id: int | None = None,
        rejection_message: str | None = None,
        account: str | None = None,
    ) -> None:
        with self.lock:
            listeners = list(self.order_status_listeners)

        payload = {
            "filled": filled,
            "remaining": remaining,
            "avg_fill_price": avg_fill_price,
            "perm_id": perm_id,
            "parent_order_id": parent_order_id,
            "rejection_message": rejection_message,
        }
        if account is not None:
            payload["account"] = account

        for listener in listeners:
            listener(order_id, status, **payload)

    def position(
        self,
        account: str,
        contract: Contract,
        position: float,
        avgCost: float,
    ) -> None:
        position_key = (account, contract.conId, contract.localSymbol)

        with self.lock:
            if position == 0:
                self.positions.pop(position_key, None)
                return

            self.positions[position_key] = PortfolioPosition(
                account=account,
                con_id=contract.conId or None,
                symbol=contract.symbol,
                sec_type=contract.secType,
                local_symbol=contract.localSymbol or None,
                expiry=contract.lastTradeDateOrContractMonth or None,
                strike=contract.strike or None,
                right=contract.right or None,
                multiplier=contract.multiplier or None,
                exchange=contract.exchange,
                currency=contract.currency,
                quantity=position,
                average_cost=clean_ib_float(avgCost),
            )

    def positionEnd(self) -> None:
        self.positions_ready.set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:
        if price <= 0:
            return

        with self.lock:
            if reqId in self.option_market_req_to_key:
                values = self.option_market_data.setdefault(reqId, {})

                if tickType in OPTION_BID_TICK_TYPES:
                    values["bid"] = price
                    self.option_market_data_ready.set()
                elif tickType in OPTION_ASK_TICK_TYPES:
                    values["ask"] = price
                    self.option_market_data_ready.set()
                elif tickType in LAST_TICK_TYPES:
                    values["last"] = price
                    self.option_market_data_ready.set()
                elif tickType in CLOSE_TICK_TYPES:
                    values["close"] = price
                    self.option_market_data_ready.set()
                return

            ticker = self.chart_market_req_tickers.get(reqId)
            if ticker is not None:
                if tickType in LAST_TICK_TYPES:
                    self.chart_market_updates_by_req_id.setdefault(reqId, []).append(
                        CompletedDailyBar(
                            ticker=ticker,
                            trading_date=datetime.now(
                                US_MARKET_TIME_ZONE,
                            ).date().isoformat(),
                            open=price,
                            high=price,
                            low=price,
                            close=price,
                        )
                    )
                    ready = self.chart_market_ready_by_req_id.get(reqId)
                    if ready is not None:
                        ready.set()
                return

            con_id = self.market_req_to_con_id.get(reqId)
            if con_id is None:
                return

            values = self.market_data.setdefault(con_id, {})

            if tickType in LAST_TICK_TYPES:
                values["last"] = price
                self.market_data_ready.set()
            elif tickType in CLOSE_TICK_TYPES:
                values["close"] = price
                self.market_data_ready.set()

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:
        with self.lock:
            if reqId not in self.option_market_req_to_key:
                return

            values = self.option_market_data.setdefault(reqId, {})
            if tickType in OPTION_BID_SIZE_TICK_TYPES:
                values["bid_size"] = size
                self.option_market_data_ready.set()
            elif tickType in OPTION_ASK_SIZE_TICK_TYPES:
                values["ask_size"] = size
                self.option_market_data_ready.set()
            elif tickType in OPTION_VOLUME_TICK_TYPES:
                values["volume"] = size
                self.option_market_data_ready.set()
            elif tickType in {27, 28}:
                values["open_interest"] = size
                self.option_market_data_ready.set()

    def tickOptionComputation(
        self,
        reqId: int,
        tickType: int,
        tickAttrib: int,
        impliedVol: float | None,
        delta: float | None,
        optPrice: float | None,
        pvDividend: float | None,
        gamma: float | None,
        vega: float | None,
        theta: float | None,
        undPrice: float | None,
    ) -> None:
        with self.lock:
            if reqId not in self.option_market_req_to_key:
                return

            values = self.option_market_data.setdefault(reqId, {})
            next_values = {
                "implied_volatility_percent": percent(
                    clean_ib_float(impliedVol),
                    1,
                ),
                "delta": clean_ib_float(delta),
                "gamma": clean_ib_float(gamma),
                "theta": clean_ib_float(theta),
            }
            model_price = clean_ib_float(optPrice)
            if tickType in {13, 83} and model_price is not None and model_price >= 0:
                next_values["model_price"] = model_price
            values.update(
                {
                    key: value
                    for key, value in next_values.items()
                    if value is not None
                }
            )
            self.option_market_data_ready.set()

    def pnlSingle(
        self,
        reqId: int,
        pos: int,
        dailyPnL: float,
        unrealizedPnL: float,
        realizedPnL: float,
        value: float,
    ) -> None:
        with self.lock:
            position_key = self.pnl_req_to_position_key.get(reqId)
            if position_key is None:
                return

            self.pnl_data[position_key] = {
                "position": clean_ib_float(pos),
                "daily_pnl": clean_ib_float(dailyPnL),
                "unrealized_pnl": clean_ib_float(unrealizedPnL),
                "realized_pnl": clean_ib_float(realizedPnL),
                "market_value": clean_ib_float(value),
            }
            self.pnl_ready.set()

    def pnl(
        self,
        reqId: int,
        dailyPnL: float,
        unrealizedPnL: float,
        realizedPnL: float,
    ) -> None:
        with self.lock:
            account = self.account_pnl_req_to_account.get(reqId)
            if account is None:
                return

            self.account_pnl_data[account] = {
                "daily_pnl": clean_ib_float(dailyPnL),
                "unrealized_pnl": clean_ib_float(unrealizedPnL),
                "realized_pnl": clean_ib_float(realizedPnL),
            }
            self.account_pnl_ready.set()

    def accountSummary(
        self,
        reqId: int,
        account: str,
        tag: str,
        value: str,
        currency: str,
    ) -> None:
        try:
            parsed_value = float(value)
        except ValueError:
            return

        with self.lock:
            pending_values = self.pending_account_summary_values.get(reqId)
            if pending_values is None:
                return

            tag_aliases = self.account_summary_tag_aliases_by_req_id.get(reqId, {})
            tag_alias = tag_aliases.get(tag)
            if tag_alias is None:
                return

            pending_values[(account, tag_alias, currency)] = parsed_value

    def accountSummaryEnd(self, reqId: int) -> None:
        with self.lock:
            if reqId != self.active_account_summary_req_id:
                return

            pending_values = self.pending_account_summary_values.pop(reqId, None)
            ready = self.account_summary_ready_by_req_id.pop(reqId, None)
            self.account_summary_tag_aliases_by_req_id.pop(reqId, None)
            if pending_values is None or ready is None:
                return

            self.account_summary_values = pending_values
            self.active_account_summary_req_id = None
            ready.set()

    def start_account_summary_request(
        self,
        req_id: int,
        *,
        initial_values: dict[tuple[str, str, str], float] | None = None,
        tag_aliases: dict[str, str] | None = None,
    ) -> tuple[threading.Event, int | None]:
        with self.lock:
            superseded_req_id = self.active_account_summary_req_id
            if superseded_req_id is not None:
                self.pending_account_summary_values.pop(superseded_req_id, None)
                self.account_summary_ready_by_req_id.pop(superseded_req_id, None)
                self.account_summary_tag_aliases_by_req_id.pop(
                    superseded_req_id,
                    None,
                )

            ready = threading.Event()
            self.pending_account_summary_values[req_id] = dict(initial_values or {})
            self.account_summary_ready_by_req_id[req_id] = ready
            self.account_summary_tag_aliases_by_req_id[req_id] = (
                tag_aliases or {tag: tag for tag in ACCOUNT_VALUE_KEYS}
            )
            self.active_account_summary_req_id = req_id
            return ready, superseded_req_id

    def abandon_account_summary_request(self, req_id: int) -> None:
        with self.lock:
            self.pending_account_summary_values.pop(req_id, None)
            self.account_summary_ready_by_req_id.pop(req_id, None)
            self.account_summary_tag_aliases_by_req_id.pop(req_id, None)
            if req_id == self.active_account_summary_req_id:
                self.active_account_summary_req_id = None

    def historicalData(self, reqId: int, bar) -> None:
        ready = None
        with self.lock:
            ticker = self.historical_req_tickers.get(reqId)
            if ticker is not None:
                completed_bar = completed_daily_bar(ticker, bar)
                if completed_bar is not None:
                    self.historical_bars.setdefault(reqId, []).append(completed_bar)
                return

            ticker = self.historical_update_req_tickers.get(reqId)
            if ticker is None:
                return

            completed_bar = completed_daily_bar(ticker, bar)
            if completed_bar is None:
                return

            self.historical_updates_by_req_id.setdefault(reqId, []).append(
                completed_bar
            )
            ready = self.historical_update_ready_by_req_id.get(reqId)

        if ready is not None:
            ready.set()

    def historicalDataUpdate(self, reqId: int, bar) -> None:
        with self.lock:
            ticker = self.historical_update_req_tickers.get(reqId)
            if ticker is None:
                return

            completed_bar = completed_daily_bar(ticker, bar)
            if completed_bar is None:
                return

            self.historical_updates_by_req_id.setdefault(reqId, []).append(
                completed_bar
            )
            ready = self.historical_update_ready_by_req_id.get(reqId)

        if ready is not None:
            ready.set()

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        with self.lock:
            ready = self.historical_data_ready_by_req_id.get(reqId)
        if ready is not None:
            ready.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:
        with self.lock:
            details = self.contract_details.get(reqId)
            if details is not None:
                details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:
        with self.lock:
            ready = self.contract_details_ready_by_req_id.get(reqId)
        if ready is not None:
            ready.set()

    def securityDefinitionOptionParameter(
        self,
        reqId: int,
        exchange: str,
        underlyingConId: int,
        tradingClass: str,
        multiplier: str,
        expirations: set[str],
        strikes: set[float],
    ) -> None:
        normalized_expirations = sorted(
            format_ib_expiration(expiration)
            for expiration in expirations
            if format_ib_expiration(expiration) is not None
        )
        normalized_strikes = sorted(strike for strike in strikes if strike > 0)

        with self.lock:
            metadata = self.option_metadata.get(reqId)
            if metadata is None:
                return

            self.option_metadata[reqId] = OptionMetadata(
                expirations=sorted(
                    set(metadata.expirations) | set(normalized_expirations)
                ),
                strikes=sorted(set(metadata.strikes) | set(normalized_strikes)),
            )

    def securityDefinitionOptionParameterEnd(self, reqId: int) -> None:
        with self.lock:
            ready = self.option_metadata_ready_by_req_id.get(reqId)
        if ready is not None:
            ready.set()

    def error(
        self,
        reqId: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        if errorCode in IB_INFO_CODES:
            logger.info(
                "IB API notice reqId=%s code=%s message=%s",
                reqId,
                errorCode,
                errorString,
            )
            return

        if errorCode in IB_DEBUG_CODES:
            logger.debug(
                "IB API notice reqId=%s code=%s message=%s",
                reqId,
                errorCode,
                errorString,
            )
            return

        warning_key = (reqId, errorCode)
        if errorCode in IB_MARKET_DATA_SUBSCRIPTION_CODES:
            with self.lock:
                if warning_key in self.logged_warnings:
                    return
                self.logged_warnings.add(warning_key)

        if errorCode in IB_INVALID_CONTRACT_CODES:
            with self.lock:
                ready = (
                    self.historical_data_ready_by_req_id.get(reqId)
                    or self.contract_details_ready_by_req_id.get(reqId)
                    or self.option_metadata_ready_by_req_id.get(reqId)
                )
                if ready is not None:
                    self.request_errors_by_req_id[reqId] = (
                        errorCode,
                        errorString,
                    )
            if ready is not None:
                ready.set()

        if errorCode in IB_HISTORICAL_NO_DATA_CODES:
            with self.lock:
                ready = self.historical_data_ready_by_req_id.get(reqId)
            if ready is not None:
                ready.set()

        with self.lock:
            is_order_error = reqId in self.submitted_order_ids
        if is_order_error:
            self._notify_order_status(
                reqId,
                "Inactive",
                rejection_message=errorString,
            )

        logger.warning(
            "IB API error reqId=%s code=%s message=%s",
            reqId,
            errorCode,
            errorString,
        )


