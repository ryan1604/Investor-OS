from dataclasses import dataclass, field
import threading
from typing import Protocol

from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionsScreener,
    OptionsScreenerFilters,
    OptionsScreenerQuoteRefreshRequest,
    OptionsScreenerQuoteRefreshResponse,
    OptionsScreenerSpreadQuoteRefreshRequest,
    OptionsScreenerSpreadQuoteRefreshResponse,
    ScreenerCandidate,
    OptionsScreenerTickerWarning,
)


class OptionsScreenerServiceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionsScreenerTickerResult:
    candidates: list[ScreenerCandidate] = field(default_factory=list)
    excluded_contracts: int = 0
    warnings: list[OptionsScreenerTickerWarning] = field(default_factory=list)


class OptionsScreenerScanService(Protocol):
    def prepare_scan(
        self,
        screener: OptionsScreener,
        tickers: tuple[str, ...],
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> None: ...

    def scan_ticker(
        self,
        screener: OptionsScreener,
        ticker: str,
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> OptionsScreenerTickerResult: ...

    def cancel(self) -> None: ...


class OptionsScreenerQuoteRefreshService(Protocol):
    def refresh_quote(
        self,
        request: OptionsScreenerQuoteRefreshRequest,
    ) -> OptionsScreenerQuoteRefreshResponse: ...


class OptionsScreenerSpreadQuoteRefreshService(Protocol):
    def refresh_spread_quote(
        self,
        request: OptionsScreenerSpreadQuoteRefreshRequest,
    ) -> OptionsScreenerSpreadQuoteRefreshResponse: ...


class OptionsScreenerService(
    OptionsScreenerScanService,
    OptionsScreenerQuoteRefreshService,
    OptionsScreenerSpreadQuoteRefreshService,
    Protocol,
):
    pass


def line_limit_warning(ticker: str, count: int) -> OptionsScreenerTickerWarning:
    return OptionsScreenerTickerWarning(
        ticker=ticker,
        category="line_limit",
        message=(
            "IB rejected contracts at the market-data line limit, so they "
            "were not quoted."
        ),
        count=count,
    )
