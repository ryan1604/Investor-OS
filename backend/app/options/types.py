from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from threading import Event
from typing import TYPE_CHECKING, Protocol

from app.options.domain import OptionMetadata
from app.options.store import CompletedDailyBar, StoredDailyBar
from app.schemas import OptionQuote

if TYPE_CHECKING:
    from app.options.rotation import OptionChainRotation


class HistoricalDailyBarProvider(Protocol):
    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        ...


class HistoricalDailyBarStreamProvider(Protocol):
    def stream_daily_bar_updates(
        self,
        ticker: str,
        stop_event: Event,
    ) -> Iterable[CompletedDailyBar]:
        ...


class OptionMetadataProvider(Protocol):
    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        ...


@dataclass(frozen=True)
class OptionChainContractHydration:
    contracts: list[ScannerOptionContract]
    timed_out_strikes: frozenset[float] = frozenset()
    invalid_strikes: frozenset[float] = frozenset()
    # Strikes left unrequested because the exact fallback was limited.
    skipped_strikes: frozenset[float] = frozenset()


class ContractLookupPriority:
    """Mark preload lookups as background until someone waits on them."""

    def __init__(self, *, background: bool = False) -> None:
        self.background = background

    def is_background(self) -> bool:
        return self.background

    def promote(self) -> None:
        self.background = False


class OptionChainSnapshotProvider(Protocol):
    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority: ContractLookupPriority | None = None,
    ) -> OptionChainContractHydration:
        ...

    def fetch_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
    ) -> dict[tuple[float, str], OptionQuote]:
        ...


class OptionChainStreamProvider(Protocol):
    def stream_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
        stop_event: Event,
        rotation: OptionChainRotation | None = None,
    ) -> Iterable[
        list[tuple[tuple[float, str], OptionQuote]] | OptionChainStreamNotice
    ]:
        ...


@dataclass(frozen=True)
class ScannerOptionContract:
    con_id: int
    ticker: str
    expiration: str
    strike: float
    right: str
    exchange: str
    currency: str
    multiplier: str
    trading_class: str
    local_symbol: str


@dataclass(frozen=True)
class ScannerOptionQuote:
    contract: ScannerOptionContract
    bid: float | None
    ask: float | None
    delta: float | None
    line_limited: bool = False


@dataclass(frozen=True)
class OptionChainStreamNotice:
    """Stream status from the provider; None clears the previous warning."""

    warning: str | None


@dataclass(frozen=True)
class ScannerContractSelection:
    contracts: list[ScannerOptionContract]
    excluded_contracts: int = 0
    invalid_lookups: frozenset[tuple[str, float]] = frozenset()
    timed_out_lookups: frozenset[tuple[str, float]] = frozenset()


class OptionScannerProvider(Protocol):
    def fetch_option_contracts(
        self,
        ticker: str,
        lookups: list[tuple[str, float]],
        right: str,
        cancel_event: Event,
    ) -> ScannerContractSelection:
        ...

    def fetch_quotes(
        self,
        contracts: list[ScannerOptionContract],
        cancel_event: Event,
    ) -> list[ScannerOptionQuote]:
        ...

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
        ...

    def cancel(self) -> None:
        ...


@dataclass(frozen=True)
class FullOptionChainSnapshot:
    ticker: str
    underlying_price: float
    underlying_price_captured_at: datetime
    contracts: list[ScannerOptionQuote]
    excluded_contracts: int = 0
    line_limited_contracts: int = 0


@dataclass(frozen=True)
class DailyBarsResult:
    ticker: str
    completed_bars: list[StoredDailyBar]
    current_bar: CompletedDailyBar | None = None
    metrics: DailyBarsMetrics | None = None


@dataclass(frozen=True)
class DailyBarsMetrics:
    cache_state: str
    history_chunk_count: int
    ib_wait_ms: float
    cache_hit_ratio: float
    payload_bytes: int


@dataclass(frozen=True)
class OptionChainContext:
    ticker: str
    expiration: str
    underlying_price: float | None
    strikes: list[float]
    contracts: list[ScannerOptionContract]


class OptionsDataUnavailable(Exception):
    pass
