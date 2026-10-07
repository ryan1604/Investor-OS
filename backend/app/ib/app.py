from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
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
from app.ib.market_data_lines import MarketDataLineBudget
from app.ib.pacing import MessagePacer, OutstandingRequestLimiter
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
MODEL_OPTION_COMPUTATION_TICK_TYPES = {13, 83}
IB_INFO_CODES = {2104, 2106, 2158}
IB_DEBUG_CODES = {2100}
IB_MARKET_DATA_SUBSCRIPTION_CODES = {10089, 10090, 10091, 10167}
IB_HISTORICAL_NO_DATA_CODES = {162}
IB_INVALID_CONTRACT_CODES = {200}
IB_MESSAGE_RATE_CODE = 100
IB_MARKET_DATA_LINE_LIMIT_CODE = 101
IB_LIMIT_CODES = {IB_MESSAGE_RATE_CODE, IB_MARKET_DATA_LINE_LIMIT_CODE}
# IB allows 50 messages per second; the margin covers unpaced requests.
IB_PACED_MESSAGES_PER_SECOND = 40
# IB answers roughly 18-35 contract lookups per second; more in flight only
# lengthens its queue until lookups time out.
IB_MAX_OUTSTANDING_CONTRACT_DETAILS = 16
# Chain preloads keep the rest free for the chain or scan someone is waiting on.
IB_MAX_BACKGROUND_CONTRACT_DETAILS = 4
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


class IbPortfolioApp(EWrapper, EClient):
    def __init__(
        self,
        *,
        market_data_line_capacity: int = 95,
        paced_messages_per_second: int = IB_PACED_MESSAGES_PER_SECOND,
    ) -> None:
        EClient.__init__(self, self)
        self.market_data_lines = MarketDataLineBudget(market_data_line_capacity)
        self.message_pacer = MessagePacer(paced_messages_per_second)
        self.contract_details_slots = OutstandingRequestLimiter(
            IB_MAX_OUTSTANDING_CONTRACT_DETAILS,
            background_capacity=IB_MAX_BACKGROUND_CONTRACT_DETAILS,
        )
        self.positions: dict[tuple[str, int, str], PortfolioPosition] = {}
        self.market_data: dict[int, dict[str, float]] = {}
        self.market_contracts: dict[int, Contract] = {}
        self.market_req_ids: dict[int, int] = {}
        self.market_req_to_con_id: dict[int, int] = {}
        # Underlying stock quotes for Portfolio Analysis, keyed by ticker.
        self.underlying_req_ids: dict[str, int] = {}
        self.underlying_req_to_symbol: dict[int, str] = {}
        self.underlying_market_data: dict[str, dict[str, float]] = {}
        self.pnl_req_ids: dict[tuple[str, int], int] = {}
        self.pnl_req_to_position_key: dict[int, tuple[str, int]] = {}
        self.pnl_data: dict[tuple[str, int], dict[str, float | None]] = {}
        self.account_pnl_req_ids: dict[str, int] = {}
        self.account_pnl_req_to_account: dict[int, str] = {}
        self.account_pnl_data: dict[str, dict[str, float | None]] = {}
        self.next_market_req_id = 10_000
        self.next_pnl_req_id = 30_000
        self.next_account_pnl_req_id = 50_000

        self.account_summary_values: dict[tuple[str, str, str], float] = {}
        self.pending_account_summary_values: dict[
            int, dict[tuple[str, str, str], float]
        ] = {}
        self.account_summary_ready_by_req_id: dict[int, threading.Event] = {}
        self.account_summary_tag_aliases_by_req_id: dict[int, dict[str, str]] = {}
        self.active_account_summary_req_id: int | None = None
        self.next_account_summary_req_id = 40_000

        self.historical_bars: dict[int, list[CompletedDailyBar]] = {}
        self.historical_req_tickers: dict[int, str] = {}
        self.historical_data_ready_by_req_id: dict[int, threading.Event] = {}
        self.historical_update_req_tickers: dict[int, str] = {}
        self.historical_updates_by_req_id: dict[int, list[CompletedDailyBar]] = {}
        self.historical_update_ready_by_req_id: dict[int, threading.Event] = {}
        self.chart_market_req_tickers: dict[int, str] = {}
        self.chart_market_updates_by_req_id: dict[
            int, list[CompletedDailyBar]
        ] = {}
        self.chart_market_ready_by_req_id: dict[int, threading.Event] = {}
        self.contract_details: dict[int, list[ContractDetails]] = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.next_historical_req_id = 60_000
        self.next_chart_market_req_id = 110_000
        self.next_contract_details_req_id = 70_000

        self.option_metadata: dict[int, OptionMetadata] = {}
        self.option_metadata_ready_by_req_id: dict[int, threading.Event] = {}
        self.option_market_req_to_key: dict[int, tuple[float, str]] = {}
        self.option_market_data: dict[int, dict[str, float | int | None]] = {}
        self.option_market_ready_by_req_id: dict[int, threading.Event] = {}
        self.next_option_params_req_id = 80_000
        self.next_option_market_req_id = 90_000
        self.active_market_data_req_ids: set[int] = set()
        self.peak_market_data_lines = 0
        self.limit_errors_by_req_id: dict[int, int] = {}
        self.limit_error_counts: dict[int, int] = {}

        self.next_order_id: int | None = None
        self.next_execution_req_id = 90_000
        self.order_status_listeners: list[Callable[..., None]] = []
        self.execution_listeners: list[Callable[..., None]] = []
        self.execution_end_listeners: list[Callable[[int], None]] = []
        self.completed_order_listeners: list[Callable[..., None]] = []
        self.completed_orders_end_listeners: list[Callable[[], None]] = []
        self.open_order_end_listeners: list[Callable[[], None]] = []
        self.submitted_order_ids: set[int] = set()
        self.logged_warnings: set[tuple[int, int]] = set()
        self.positions_ready = threading.Event()
        self.market_data_ready = threading.Event()
        self.pnl_ready = threading.Event()
        self.account_pnl_ready = threading.Event()
        self.connected_ready = threading.Event()
        self.lock = threading.Lock()

    def nextValidId(self, orderId: int) -> None:
        with self.lock:
            self.next_order_id = orderId
        self.connected_ready.set()

    def reqContractDetails(self, reqId: int, contract: Contract) -> None:
        self.message_pacer.wait()
        super().reqContractDetails(reqId, contract)

    def reqHistoricalData(self, reqId: int, *args, **kwargs) -> None:
        self.message_pacer.wait()
        super().reqHistoricalData(reqId, *args, **kwargs)

    def reqMktData(self, reqId: int, *args, **kwargs) -> None:
        self.message_pacer.wait()
        with self.lock:
            self.active_market_data_req_ids.add(reqId)
            self.peak_market_data_lines = max(
                self.peak_market_data_lines,
                len(self.active_market_data_req_ids),
            )
        super().reqMktData(reqId, *args, **kwargs)

    def cancelMktData(self, reqId: int) -> None:
        self.message_pacer.wait()
        with self.lock:
            self.active_market_data_req_ids.discard(reqId)
        super().cancelMktData(reqId)

    def market_data_line_usage(self) -> tuple[int, int]:
        with self.lock:
            return len(self.active_market_data_req_ids), self.peak_market_data_lines

    def limit_error_count(self, req_ids: Iterable[int]) -> dict[int, int]:
        with self.lock:
            counts: dict[int, int] = {}
            for req_id in req_ids:
                code = self.limit_errors_by_req_id.get(req_id)
                if code is not None:
                    counts[code] = counts.get(code, 0) + 1
            return counts

    def add_order_status_listener(self, listener: Callable[..., None]) -> None:
        with self.lock:
            self.order_status_listeners.append(listener)

    def add_open_order_end_listener(self, listener: Callable[[], None]) -> None:
        with self.lock:
            self.open_order_end_listeners.append(listener)

    def add_execution_listener(self, listener: Callable[..., None]) -> None:
        with self.lock:
            self.execution_listeners.append(listener)

    def add_execution_end_listener(self, listener: Callable[[int], None]) -> None:
        with self.lock:
            self.execution_end_listeners.append(listener)

    def add_completed_order_listener(self, listener: Callable[..., None]) -> None:
        with self.lock:
            self.completed_order_listeners.append(listener)

    def add_completed_orders_end_listener(self, listener: Callable[[], None]) -> None:
        with self.lock:
            self.completed_orders_end_listeners.append(listener)

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
            contract=contract,
            order=order,
            order_state=orderState,
        )

    def openOrderEnd(self) -> None:
        with self.lock:
            listeners = list(self.open_order_end_listeners)

        for listener in listeners:
            listener()

    def execDetails(self, reqId: int, contract: Contract, execution) -> None:
        with self.lock:
            listeners = list(self.execution_listeners)

        payload = {
            "req_id": reqId,
            "contract": contract,
            "execution_id": getattr(execution, "execId", "") or None,
            "order_id": getattr(execution, "orderId", 0) or 0,
            "perm_id": getattr(execution, "permId", 0) or None,
            "account": getattr(execution, "acctNumber", "") or None,
            "side": getattr(execution, "side", "") or None,
            "shares": clean_ib_float(getattr(execution, "shares", None)),
            "price": clean_ib_price(getattr(execution, "price", None)),
            "avg_price": clean_ib_price(getattr(execution, "avgPrice", None)),
            "cumulative_quantity": clean_ib_float(getattr(execution, "cumQty", None)),
            "execution_time": getattr(execution, "time", "") or None,
        }
        for listener in listeners:
            listener(**payload)

    def execDetailsEnd(self, reqId: int) -> None:
        with self.lock:
            listeners = list(self.execution_end_listeners)

        for listener in listeners:
            listener(reqId)

    def completedOrder(self, contract: Contract, order, orderState) -> None:
        with self.lock:
            listeners = list(self.completed_order_listeners)

        for listener in listeners:
            listener(contract=contract, order=order, order_state=orderState)

    def completedOrdersEnd(self) -> None:
        with self.lock:
            listeners = list(self.completed_orders_end_listeners)

        for listener in listeners:
            listener()

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
        contract: Contract | None = None,
        order=None,
        order_state=None,
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
        if contract is not None:
            payload["contract"] = contract
        if order is not None:
            payload["order"] = order
        if order_state is not None:
            payload["order_state"] = order_state

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
                elif tickType in OPTION_ASK_TICK_TYPES:
                    values["ask"] = price
                elif tickType in LAST_TICK_TYPES:
                    values["last"] = price
                elif tickType in CLOSE_TICK_TYPES:
                    values["close"] = price
                else:
                    return
                self._signal_option_market_data(reqId)
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

            symbol = self.underlying_req_to_symbol.get(reqId)
            if symbol is not None:
                values = self.underlying_market_data.setdefault(symbol, {})
                if tickType in LAST_TICK_TYPES:
                    values["last"] = price
                elif tickType in CLOSE_TICK_TYPES:
                    values["close"] = price
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
            elif tickType in OPTION_ASK_SIZE_TICK_TYPES:
                values["ask_size"] = size
            elif tickType in OPTION_VOLUME_TICK_TYPES:
                values["volume"] = size
            elif tickType in {27, 28}:
                values["open_interest"] = size
            else:
                return
            self._signal_option_market_data(reqId)

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
            con_id = self.market_req_to_con_id.get(reqId)
            if con_id is not None:
                self._store_position_greeks(
                    con_id,
                    tickType,
                    impliedVol,
                    delta,
                    gamma,
                    vega,
                    theta,
                    undPrice,
                )
                return

            if reqId not in self.option_market_req_to_key:
                return
            # Bid, ask, and last computations solve IV from that one price, so a
            # wide quote skews their delta; only IB's model Greeks are kept. IB
            # sends the model tick first, so this does not delay any field.
            if tickType not in MODEL_OPTION_COMPUTATION_TICK_TYPES:
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
            if model_price is not None and model_price >= 0:
                next_values["model_price"] = model_price
            values.update(
                {
                    key: value
                    for key, value in next_values.items()
                    if value is not None
                }
            )
            self._signal_option_market_data(reqId)

    def _store_position_greeks(
        self,
        con_id: int,
        tick_type: int,
        implied_vol: float | None,
        delta: float | None,
        gamma: float | None,
        vega: float | None,
        theta: float | None,
        underlying_price: float | None,
    ) -> None:
        """Keep a portfolio option's Greeks, letting model ticks win over quote ticks."""
        values = self.market_data.setdefault(con_id, {})
        is_model = tick_type in MODEL_OPTION_COMPUTATION_TICK_TYPES
        if not is_model and values.get("greeks_from_model"):
            return

        next_values = {
            "implied_volatility": clean_ib_float(implied_vol),
            "delta": clean_ib_float(delta),
            "gamma": clean_ib_float(gamma),
            "vega": clean_ib_float(vega),
            "theta": clean_ib_float(theta),
            "underlying_price": clean_ib_price(underlying_price or 0),
        }
        values.update(
            {key: value for key, value in next_values.items() if value is not None}
        )
        if is_model:
            values["greeks_from_model"] = 1.0

    def _signal_option_market_data(self, req_id: int) -> None:
        # Each subscription group waits on its own event, so one group's
        # wakeups are never cleared by another group.
        ready = self.option_market_ready_by_req_id.get(req_id)
        if ready is not None:
            ready.set()

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
        self.contract_details_slots.release(reqId)
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
        self.contract_details_slots.release(reqId)
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

        if errorCode in IB_LIMIT_CODES:
            with self.lock:
                self.limit_errors_by_req_id[reqId] = errorCode
                self.limit_error_counts[errorCode] = (
                    self.limit_error_counts.get(errorCode, 0) + 1
                )
                if errorCode == IB_MARKET_DATA_LINE_LIMIT_CODE:
                    self.active_market_data_req_ids.discard(reqId)
                    self._signal_option_market_data(reqId)

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


