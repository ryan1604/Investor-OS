import threading
from typing import Protocol

from app.config import Settings
from app.ib.daily_bars import (
    IbHistoricalDailyBarProvider,
    IbHistoricalDailyBarStreamProvider,
)
from app.ib.option_scanner import IbOptionScannerProvider
from app.ib.options import (
    IbOptionChainSnapshotProvider,
    IbOptionChainStreamProvider,
    IbOptionMetadataProvider,
)
from app.ib.portfolio import PortfolioClient
from app.options.client import OptionsClient
from app.options.store import OptionsDailyBarStore
from app.schemas import (
    OptionChainResponse,
    OptionExpirationsResponse,
    OptionsAnalysisResponse,
)


class OptionsAnalysisClient(Protocol):
    def shutdown(self) -> None:
        ...

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        ...

    def get_underlying_price(self, ticker: str) -> float:
        ...

    def get_expirations(self, ticker: str) -> OptionExpirationsResponse:
        ...

    def get_chain(self, ticker: str, expiration: str) -> OptionChainResponse:
        ...

    def stream_chain(
        self,
        ticker: str,
        expiration: str,
        *,
        stop_event: threading.Event,
    ):
        ...

    def stream_chart(
        self,
        ticker: str,
        *,
        stop_event: threading.Event,
    ):
        ...


def create_options_client(
    settings: Settings,
    client: PortfolioClient,
) -> OptionsClient:
    app = getattr(client, "app", None)
    if app is None:
        raise RuntimeError("Options client requires an IB app.")

    return OptionsClient(
        OptionsDailyBarStore(settings.options_database_path),
        historical_provider=IbHistoricalDailyBarProvider(app),
        metadata_provider=IbOptionMetadataProvider(app),
        chain_provider=IbOptionChainSnapshotProvider(app),
        chain_stream_provider=IbOptionChainStreamProvider(
            app,
            rotation_lines=settings.option_chain_rotation_lines,
        ),
        historical_stream_provider=IbHistoricalDailyBarStreamProvider(app),
        scanner_provider=IbOptionScannerProvider(app),
        chain_context_workers=settings.option_chain_context_workers,
        max_chain_strikes=settings.max_option_chain_strikes,
        max_chain_stream_strikes=settings.max_option_chain_stream_strikes,
    )
