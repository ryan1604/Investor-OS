from __future__ import annotations

import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from ibapi.client import EClient
from ibapi.contract import ContractDetails
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


class IbPortfolioApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.positions: dict[tuple[str, int, str], PortfolioPosition] = {}
        self.account_summary_values: dict[tuple[str, str, str], float] = {}
        self.pending_account_summary_values: dict[
            int,
            dict[tuple[str, str, str], float],
        ] = {}
        self.account_summary_ready_by_req_id: dict[int, threading.Event] = {}
        self.account_summary_tag_aliases_by_req_id: dict[int, dict[str, str]] = {}
        self.active_account_summary_req_id: int | None = None
        self.market_data: dict[int, dict[str, float]] = {}
        self.market_contracts: dict[int, Contract] = {}
        self.market_req_ids: dict[int, int] = {}
        self.market_req_to_con_id: dict[int, int] = {}
        self.pnl_req_ids: dict[tuple[str, int], int] = {}
        self.pnl_req_to_position_key: dict[int, tuple[str, int]] = {}
        self.pnl_data: dict[tuple[str, int], dict[str, float | None]] = {}
        self.account_pnl_req_ids: dict[str, int] = {}
        self.account_pnl_req_to_account: dict[int, str] = {}
        self.account_pnl_data: dict[str, dict[str, float | None]] = {}
        self.next_market_req_id = 10_000
        self.next_pnl_req_id = 30_000
        self.next_account_summary_req_id = 40_000
        self.next_account_pnl_req_id = 50_000
        self.next_historical_req_id = 60_000
        self.next_chart_market_req_id = 110_000
        self.next_contract_details_req_id = 70_000
        self.next_option_params_req_id = 80_000
        self.next_option_market_req_id = 90_000
        self.logged_warnings: set[tuple[int, int]] = set()
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.historical_bars: dict[int, list[CompletedDailyBar]] = {}
        self.historical_req_tickers: dict[int, str] = {}
        self.historical_data_ready_by_req_id: dict[int, threading.Event] = {}
        self.historical_update_req_tickers: dict[int, str] = {}
        self.historical_updates_by_req_id: dict[int, list[CompletedDailyBar]] = {}
        self.historical_update_ready_by_req_id: dict[int, threading.Event] = {}
        self.chart_market_req_tickers: dict[int, str] = {}
        self.chart_market_updates_by_req_id: dict[int, list[CompletedDailyBar]] = {}
        self.chart_market_ready_by_req_id: dict[int, threading.Event] = {}
        self.contract_details: dict[int, list[ContractDetails]] = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.option_metadata: dict[int, OptionMetadata] = {}
        self.option_metadata_ready_by_req_id: dict[int, threading.Event] = {}
        self.option_market_req_to_key: dict[int, tuple[float, str]] = {}
        self.option_market_data: dict[int, dict[str, float | int | None]] = {}
        self.positions_ready = threading.Event()
        self.market_data_ready = threading.Event()
        self.pnl_ready = threading.Event()
        self.account_pnl_ready = threading.Event()
        self.option_market_data_ready = threading.Event()
        self.connected_ready = threading.Event()
        self.lock = threading.Lock()

    def nextValidId(self, orderId: int) -> None:
        self.connected_ready.set()

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

        logger.warning(
            "IB API error reqId=%s code=%s message=%s",
            reqId,
            errorCode,
            errorString,
        )


