from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
import logging
import threading
from time import perf_counter
from typing import Protocol

from app.options.types import (
    FullOptionChainSnapshot,
    OptionsDataUnavailable,
    ScannerOptionQuote,
)
from app.options.rotation import option_contract_preference
from app.options_screeners.domain import (
    build_cc_candidate,
    build_csp_candidate,
    finite_values,
    matches_filters,
    positive_finite,
    sort_candidates,
)
from app.options_screeners.service import (
    OptionsScreenerServiceUnavailable,
    OptionsScreenerTickerResult,
    line_limit_warning,
)
from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionContractIdentity,
    OptionsScreener,
    OptionsScreenerFilters,
    OptionsScreenerQuoteRefreshRequest,
    OptionsScreenerQuoteRefreshResponse,
    OptionsScreenerTickerWarning,
)
from app.sessions import US_MARKET_TIME_ZONE

logger = logging.getLogger(__name__)


class FullOptionChainClient(Protocol):
    def get_full_option_chain(
        self,
        ticker: str,
        *,
        right: str,
        minimum_dte: int,
        maximum_dte: int,
        cancel_event: threading.Event,
        current_date: date | None = None,
    ) -> FullOptionChainSnapshot:
        ...

    def cancel_scanner(self) -> None:
        ...

    def refresh_option_quote(
        self,
        *,
        ticker: str,
        expiration: str,
        strike: float,
        right: str,
        con_id: int | None,
        local_symbol: str | None,
    ) -> ScannerOptionQuote:
        ...


class SingleLegOptionsScreenerScanService:
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
        if screener not in {"csp", "cc"}:
            raise OptionsScreenerServiceUnavailable(
                f"{screener.upper()} scanning is not available yet."
            )

    def scan_ticker(
        self,
        screener: OptionsScreener,
        ticker: str,
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> OptionsScreenerTickerResult:
        if screener not in {"csp", "cc"}:
            raise OptionsScreenerServiceUnavailable(
                f"{screener.upper()} scanning is not available yet."
            )

        current_date = self.current_date_provider()
        started_at = perf_counter()
        snapshot = self.client.get_full_option_chain(
            ticker,
            right="P" if screener == "csp" else "C",
            minimum_dte=filters.minimum_dte,
            maximum_dte=filters.maximum_dte,
            cancel_event=cancel_event,
            current_date=current_date,
        )
        deduplicated = deduplicate_quotes(snapshot.contracts)
        excluded_contracts = (
            snapshot.excluded_contracts
            + len(snapshot.contracts)
            - len(deduplicated)
        )
        candidates = []

        for quote in deduplicated:
            if cancel_event.is_set():
                break
            dte = contract_dte(quote.contract.expiration, current_date)
            if not valid_single_leg_quote(
                quote,
                snapshot.underlying_price,
                dte,
                screener=screener,
            ):
                excluded_contracts += 1
                continue

            candidate_builder = (
                build_csp_candidate
                if screener == "csp"
                else build_cc_candidate
            )
            candidate = candidate_builder(
                ticker=snapshot.ticker,
                stock_price=snapshot.underlying_price,
                strike=quote.contract.strike,
                expiration=quote.contract.expiration,
                dte=dte,
                delta=quote.delta,
                bid=quote.bid,
                ask=quote.ask,
                contract=OptionContractIdentity(
                    con_id=quote.contract.con_id,
                    local_symbol=quote.contract.local_symbol,
                ),
            )
            if candidate is None:
                excluded_contracts += 1
                continue
            if matches_filters(
                dte=candidate.dte,
                delta=candidate.delta,
                annualized_return=candidate.annualized_return,
                filters=filters,
            ):
                candidates.append(candidate)

        warnings = []
        if excluded_contracts:
            warnings.append(
                OptionsScreenerTickerWarning(
                    ticker=snapshot.ticker,
                    category="excluded_contracts",
                    message=(
                        "Contracts were excluded because they were duplicate, "
                        "nonstandard, missing data, or had an invalid market."
                    ),
                    count=excluded_contracts,
                )
            )
        if snapshot.line_limited_contracts:
            warnings.append(
                line_limit_warning(snapshot.ticker, snapshot.line_limited_contracts)
            )
        if not candidates:
            warnings.append(
                OptionsScreenerTickerWarning(
                    ticker=snapshot.ticker,
                    category="no_matches",
                    message="No contracts matched the saved filters.",
                )
            )
        logger.info(
            "Options screener ticker scanned screener=%s ticker=%s "
            "candidates=%s excluded_contracts=%s elapsed_ms=%.1f",
            screener,
            snapshot.ticker,
            len(candidates),
            excluded_contracts,
            (perf_counter() - started_at) * 1_000,
        )
        return OptionsScreenerTickerResult(
            candidates=sort_candidates(candidates),
            excluded_contracts=excluded_contracts,
            warnings=warnings,
        )

    def cancel(self) -> None:
        self.client.cancel_scanner()

    def refresh_quote(
        self,
        request: OptionsScreenerQuoteRefreshRequest,
    ) -> OptionsScreenerQuoteRefreshResponse:
        try:
            quote = self.client.refresh_option_quote(
                ticker=request.ticker,
                expiration=request.expiration,
                strike=request.strike,
                right="P" if request.right == "PUT" else "C",
                con_id=request.contract.con_id,
                local_symbol=request.contract.local_symbol,
            )
        except OptionsDataUnavailable as error:
            raise OptionsScreenerServiceUnavailable(str(error)) from error

        midpoint = refreshed_midpoint(quote)
        if midpoint is None:
            raise OptionsScreenerServiceUnavailable(
                "The selected option contract does not have a valid current quote."
            )

        return OptionsScreenerQuoteRefreshResponse(
            ticker=quote.contract.ticker,
            expiration=quote.contract.expiration,
            strike=quote.contract.strike,
            right="PUT" if quote.contract.right in {"P", "PUT"} else "CALL",
            contract=OptionContractIdentity(
                con_id=quote.contract.con_id,
                local_symbol=quote.contract.local_symbol,
            ),
            bid=quote.bid,
            ask=quote.ask,
            midpoint=midpoint,
            delta=quote.delta,
            refreshed_at=datetime.now(UTC).isoformat(),
        )

def contract_dte(expiration: str, current_date: date) -> int | None:
    try:
        return (date.fromisoformat(expiration) - current_date).days
    except ValueError:
        return None


def valid_single_leg_quote(
    quote: ScannerOptionQuote,
    underlying_price: float,
    dte: int | None,
    *,
    screener: OptionsScreener,
) -> bool:
    contract = quote.contract
    expected_rights = {"P", "PUT"} if screener == "csp" else {"C", "CALL"}
    is_otm = (
        contract.strike < underlying_price
        if screener == "csp"
        else contract.strike > underlying_price
    )
    values = (
        underlying_price,
        contract.strike,
        quote.bid,
        quote.ask,
        quote.delta,
    )
    return (
        contract.right in expected_rights
        and contract.currency == "USD"
        and contract.multiplier == "100"
        and contract.trading_class == contract.ticker
        and is_otm
        and dte is not None
        and dte > 0
        and all(value is not None for value in values)
        and finite_values(*values)
        and positive_finite(quote.bid)
        and quote.ask >= quote.bid
        and ((quote.bid + quote.ask) / 2) > 0
    )


def deduplicate_quotes(
    quotes: list[ScannerOptionQuote],
) -> list[ScannerOptionQuote]:
    selected: dict[tuple[str, float, str, str], ScannerOptionQuote] = {}
    for quote in quotes:
        contract = quote.contract
        key = (
            contract.expiration,
            contract.strike,
            contract.right,
            contract.multiplier,
        )
        current = selected.get(key)
        if current is None or option_contract_preference(
            quote.contract
        ) < option_contract_preference(current.contract):
            selected[key] = quote
    return list(selected.values())


def refreshed_midpoint(quote: ScannerOptionQuote) -> float | None:
    if (
        not positive_finite(quote.bid)
        or quote.ask is None
        or not finite_values(quote.ask)
        or quote.ask < quote.bid
    ):
        return None
    return (quote.bid + quote.ask) / 2
