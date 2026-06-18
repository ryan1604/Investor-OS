from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
import math
import threading

from app.options.client import (
    FullOptionChainSnapshot,
    OptionsDataUnavailable,
    ScannerOptionQuote,
)
from app.options_screeners.domain import (
    build_credit_spread_candidate,
    matches_filters,
    sort_candidates,
    spread_pricing,
)
from app.options_screeners.service import (
    OptionsScreenerScanService,
    OptionsScreenerServiceUnavailable,
    OptionsScreenerTickerResult,
)
from app.options_screeners.single_leg import (
    FullOptionChainClient,
    SingleLegOptionsScreenerScanService,
    US_MARKET_TIME_ZONE,
    contract_dte,
    quote_preference,
)
from app.schemas import (
    CreditSpreadScreenerFilters,
    CreditSpreadStrategy,
    OptionContractIdentity,
    OptionsScreener,
    OptionsScreenerFilters,
    OptionsScreenerSpreadQuoteRefreshRequest,
    OptionsScreenerSpreadQuoteRefreshResponse,
    OptionsScreenerTickerWarning,
)

WIDTH_TOLERANCE = 1e-6


class CreditSpreadOptionsScreenerScanService:
    def __init__(
        self,
        client: FullOptionChainClient,
        *,
        current_date_provider: Callable[[], date] | None = None,
    ) -> None:
        self.client = client
        self.current_date_provider = current_date_provider or (
            lambda: datetime.now(US_MARKET_TIME_ZONE).date()
        )

    def prepare_scan(
        self,
        screener: OptionsScreener,
        tickers: tuple[str, ...],
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> None:
        if screener != "cs":
            raise OptionsScreenerServiceUnavailable(
                f"{screener.upper()} scanning is not available yet."
            )
        if not isinstance(filters, CreditSpreadScreenerFilters):
            raise OptionsScreenerServiceUnavailable(
                "Credit spread filters are required for CS scanning."
            )

    def scan_ticker(
        self,
        screener: OptionsScreener,
        ticker: str,
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> OptionsScreenerTickerResult:
        self.prepare_scan(screener, (ticker,), filters, cancel_event)
        assert isinstance(filters, CreditSpreadScreenerFilters)

        current_date = self.current_date_provider()
        candidates = []
        excluded_contracts = 0

        for right, strategy in strategy_requests(filters.strategy_types):
            if cancel_event.is_set():
                break
            try:
                snapshot = self.client.get_full_option_chain(
                    ticker,
                    right=right,
                    minimum_dte=filters.minimum_dte,
                    maximum_dte=filters.maximum_dte,
                    cancel_event=cancel_event,
                    current_date=current_date,
                )
            except OptionsDataUnavailable as error:
                raise OptionsScreenerServiceUnavailable(str(error)) from error

            result = scan_spread_snapshot(
                snapshot,
                strategy=strategy,
                filters=filters,
                current_date=current_date,
                cancel_event=cancel_event,
            )
            candidates.extend(result.candidates)
            excluded_contracts += snapshot.excluded_contracts
            excluded_contracts += result.excluded_contracts

        warnings = []
        if excluded_contracts:
            warnings.append(
                OptionsScreenerTickerWarning(
                    ticker=ticker,
                    category="excluded_contracts",
                    message=(
                        "Contracts or spreads were excluded because they were "
                        "duplicate, nonstandard, missing data, non-exact width, "
                        "or had an invalid net-credit market."
                    ),
                    count=excluded_contracts,
                )
            )
        if not candidates:
            warnings.append(
                OptionsScreenerTickerWarning(
                    ticker=ticker,
                    category="no_matches",
                    message="No credit spreads matched the saved filters.",
                )
            )
        return OptionsScreenerTickerResult(
            candidates=sort_candidates(candidates),
            excluded_contracts=excluded_contracts,
            warnings=warnings,
        )

    def cancel(self) -> None:
        cancel_scanner = getattr(self.client, "cancel_scanner", None)
        if cancel_scanner is not None:
            cancel_scanner()

    def refresh_spread_quote(
        self,
        request: OptionsScreenerSpreadQuoteRefreshRequest,
    ) -> OptionsScreenerSpreadQuoteRefreshResponse:
        right = "P" if request.strategy == "put_credit_spread" else "C"
        response_right = "PUT" if right == "P" else "CALL"
        try:
            short_quote = self.client.refresh_option_quote(
                ticker=request.ticker,
                expiration=request.expiration,
                strike=request.short_strike,
                right=right,
                con_id=request.short_contract.con_id,
                local_symbol=request.short_contract.local_symbol,
            )
            long_quote = self.client.refresh_option_quote(
                ticker=request.ticker,
                expiration=request.expiration,
                strike=request.long_strike,
                right=right,
                con_id=request.long_contract.con_id,
                local_symbol=request.long_contract.local_symbol,
            )
        except OptionsDataUnavailable as error:
            raise OptionsScreenerServiceUnavailable(str(error)) from error

        if not compatible_refreshed_spread(short_quote, long_quote, request.strategy):
            raise OptionsScreenerServiceUnavailable(
                "The selected spread legs can no longer be resolved as a compatible pair."
            )

        pricing = spread_pricing(
            short_quote.bid,
            short_quote.ask,
            long_quote.bid,
            long_quote.ask,
        )
        if pricing is None:
            raise OptionsScreenerServiceUnavailable(
                "The selected spread no longer has a valid net-credit market."
            )

        width = abs(short_quote.contract.strike - long_quote.contract.strike)
        if pricing.midpoint >= width:
            raise OptionsScreenerServiceUnavailable(
                "The selected spread no longer has positive maximum loss."
            )

        return OptionsScreenerSpreadQuoteRefreshResponse(
            strategy=request.strategy,
            ticker=short_quote.contract.ticker,
            expiration=short_quote.contract.expiration,
            right=response_right,
            short_strike=short_quote.contract.strike,
            long_strike=long_quote.contract.strike,
            short_contract=OptionContractIdentity(
                con_id=short_quote.contract.con_id,
                local_symbol=short_quote.contract.local_symbol,
            ),
            long_contract=OptionContractIdentity(
                con_id=long_quote.contract.con_id,
                local_symbol=long_quote.contract.local_symbol,
            ),
            short_bid=short_quote.bid,
            short_ask=short_quote.ask,
            short_midpoint=(short_quote.bid + short_quote.ask) / 2,
            long_bid=long_quote.bid,
            long_ask=long_quote.ask,
            long_midpoint=(long_quote.bid + long_quote.ask) / 2,
            short_delta=short_quote.delta,
            net_bid=pricing.net_bid,
            net_ask=pricing.net_ask,
            net_midpoint=pricing.midpoint,
            maximum_loss=width - pricing.midpoint,
            refreshed_at=datetime.now(US_MARKET_TIME_ZONE).isoformat(),
        )


class CombinedOptionsScreenerScanService:
    def __init__(
        self,
        single_leg_service: SingleLegOptionsScreenerScanService,
        credit_spread_service: CreditSpreadOptionsScreenerScanService,
    ) -> None:
        self.single_leg_service = single_leg_service
        self.credit_spread_service = credit_spread_service

    def prepare_scan(
        self,
        screener: OptionsScreener,
        tickers: tuple[str, ...],
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> None:
        self._service(screener).prepare_scan(
            screener,
            tickers,
            filters,
            cancel_event,
        )

    def scan_ticker(
        self,
        screener: OptionsScreener,
        ticker: str,
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> OptionsScreenerTickerResult:
        return self._service(screener).scan_ticker(
            screener,
            ticker,
            filters,
            cancel_event,
        )

    def cancel(self) -> None:
        self.single_leg_service.cancel()
        self.credit_spread_service.cancel()

    def refresh_quote(
        self,
        request: OptionsScreenerQuoteRefreshRequest,
    ) -> OptionsScreenerQuoteRefreshResponse:
        return self.single_leg_service.refresh_quote(request)

    def refresh_spread_quote(
        self,
        request: OptionsScreenerSpreadQuoteRefreshRequest,
    ) -> OptionsScreenerSpreadQuoteRefreshResponse:
        return self.credit_spread_service.refresh_spread_quote(request)

    def _service(self, screener: OptionsScreener) -> OptionsScreenerScanService:
        if screener == "cs":
            return self.credit_spread_service
        return self.single_leg_service


def strategy_requests(
    strategy_types: list[CreditSpreadStrategy],
) -> list[tuple[str, CreditSpreadStrategy]]:
    requests: list[tuple[str, CreditSpreadStrategy]] = []
    if "put_credit_spread" in strategy_types:
        requests.append(("P", "put_credit_spread"))
    if "call_credit_spread" in strategy_types:
        requests.append(("C", "call_credit_spread"))
    return requests


def scan_spread_snapshot(
    snapshot: FullOptionChainSnapshot,
    *,
    strategy: CreditSpreadStrategy,
    filters: CreditSpreadScreenerFilters,
    current_date: date,
    cancel_event: threading.Event,
) -> OptionsScreenerTickerResult:
    excluded_contracts = 0
    quotes_by_expiration: dict[str, list[ScannerOptionQuote]] = defaultdict(list)
    valid_quotes = []

    for quote in snapshot.contracts:
        dte = contract_dte(quote.contract.expiration, current_date)
        if not valid_spread_leg_quote(
            quote,
            snapshot.underlying_price,
            dte,
            strategy=strategy,
        ):
            excluded_contracts += 1
            continue
        valid_quotes.append(quote)
        quotes_by_expiration[quote.contract.expiration].append(quote)

    candidates = []
    emitted_keys: set[tuple[str, str, float, float]] = set()
    for quote in sorted(valid_quotes, key=quote_preference):
        if cancel_event.is_set():
            break
        short_dte = contract_dte(quote.contract.expiration, current_date)
        if not short_leg_is_otm(
            strategy,
            quote.contract.strike,
            snapshot.underlying_price,
        ):
            continue

        for width in filters.spread_widths:
            long_strike = expected_long_strike(
                strategy,
                quote.contract.strike,
                width,
            )
            long_quote = find_long_quote(
                quotes_by_expiration[quote.contract.expiration],
                short_quote=quote,
                long_strike=long_strike,
            )
            if long_quote is None:
                excluded_contracts += 1
                continue

            key = (
                strategy,
                quote.contract.expiration,
                quote.contract.strike,
                long_quote.contract.strike,
            )
            if key in emitted_keys:
                excluded_contracts += 1
                continue
            emitted_keys.add(key)

            candidate = build_credit_spread_candidate(
                strategy=strategy,
                ticker=snapshot.ticker,
                stock_price=snapshot.underlying_price,
                short_strike=quote.contract.strike,
                long_strike=long_quote.contract.strike,
                expiration=quote.contract.expiration,
                dte=short_dte,
                short_delta=quote.delta,
                short_bid=quote.bid,
                short_ask=quote.ask,
                long_bid=long_quote.bid,
                long_ask=long_quote.ask,
                short_contract=OptionContractIdentity(
                    con_id=quote.contract.con_id,
                    local_symbol=quote.contract.local_symbol,
                ),
                long_contract=OptionContractIdentity(
                    con_id=long_quote.contract.con_id,
                    local_symbol=long_quote.contract.local_symbol,
                ),
            )
            if candidate is None:
                excluded_contracts += 1
                continue
            if matches_filters(
                dte=candidate.dte,
                delta=candidate.short_delta,
                annualized_return=candidate.annualized_return,
                filters=filters,
            ):
                candidates.append(candidate)

    return OptionsScreenerTickerResult(
        candidates=candidates,
        excluded_contracts=excluded_contracts,
    )


def valid_spread_leg_quote(
    quote: ScannerOptionQuote,
    underlying_price: float,
    dte: int | None,
    *,
    strategy: CreditSpreadStrategy,
) -> bool:
    contract = quote.contract
    expected_rights = (
        {"P", "PUT"} if strategy == "put_credit_spread" else {"C", "CALL"}
    )
    values = (
        underlying_price,
        contract.strike,
        quote.bid,
        quote.ask,
    )
    return (
        contract.right in expected_rights
        and contract.currency == "USD"
        and contract.multiplier == "100"
        and dte is not None
        and dte > 0
        and all(value is not None and math.isfinite(value) for value in values)
        and quote.bid >= 0
        and quote.ask >= quote.bid
    )


def short_leg_is_otm(
    strategy: CreditSpreadStrategy,
    strike: float,
    underlying_price: float,
) -> bool:
    if strategy == "put_credit_spread":
        return strike < underlying_price
    return strike > underlying_price


def expected_long_strike(
    strategy: CreditSpreadStrategy,
    short_strike: float,
    width: float,
) -> float:
    if strategy == "put_credit_spread":
        return short_strike - width
    return short_strike + width


def find_long_quote(
    quotes: list[ScannerOptionQuote],
    *,
    short_quote: ScannerOptionQuote,
    long_strike: float,
) -> ScannerOptionQuote | None:
    compatible = [
        quote
        for quote in quotes
        if quote.contract.ticker == short_quote.contract.ticker
        and quote.contract.expiration == short_quote.contract.expiration
        and quote.contract.right == short_quote.contract.right
        and quote.contract.multiplier == short_quote.contract.multiplier
        and quote.contract.trading_class == short_quote.contract.trading_class
        and abs(quote.contract.strike - long_strike) <= WIDTH_TOLERANCE
    ]
    return min(
        compatible,
        key=lambda quote: (
            0 if quote.contract.exchange == "SMART" else 1,
            quote.contract.con_id,
        ),
        default=None,
    )


def compatible_refreshed_spread(
    short_quote: ScannerOptionQuote,
    long_quote: ScannerOptionQuote,
    strategy: CreditSpreadStrategy,
) -> bool:
    short_contract = short_quote.contract
    long_contract = long_quote.contract
    expected_rights = (
        {"P", "PUT"} if strategy == "put_credit_spread" else {"C", "CALL"}
    )
    expected_order = (
        short_contract.strike > long_contract.strike
        if strategy == "put_credit_spread"
        else short_contract.strike < long_contract.strike
    )
    values = (
        short_quote.bid,
        short_quote.ask,
        long_quote.bid,
        long_quote.ask,
        short_contract.strike,
        long_contract.strike,
    )
    return (
        short_contract.ticker == long_contract.ticker
        and short_contract.expiration == long_contract.expiration
        and short_contract.right in expected_rights
        and long_contract.right in expected_rights
        and short_contract.currency == "USD"
        and long_contract.currency == "USD"
        and short_contract.multiplier == "100"
        and long_contract.multiplier == "100"
        and short_contract.trading_class == long_contract.trading_class
        and expected_order
        and all(value is not None and math.isfinite(value) for value in values)
    )
