import threading
from collections.abc import Callable
from typing import Protocol

from app.config import Settings
from app.ib.options import (
    IbHistoricalDailyBarProvider,
    IbHistoricalDailyBarStreamProvider,
    IbOptionChainSnapshotProvider,
    IbOptionChainStreamProvider,
    IbOptionMetadataProvider,
)
from app.ib.portfolio import PortfolioClient
from app.options.client import (
    OptionsClient,
    OptionsDataUnavailable,
    UnavailableHistoricalDailyBarStreamProvider,
    UnavailableOptionChainSnapshotProvider,
    UnavailableOptionChainStreamProvider,
    UnavailableOptionMetadataProvider,
)
from app.options.store import OptionsDailyBarStore
from app.schemas import (
    OptionChainResponse,
    OptionExpirationsResponse,
    OptionsAnalysisResponse,
)


class OptionsAnalysisClient(Protocol):
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


OptionsClientFactory = Callable[[Settings, PortfolioClient], OptionsAnalysisClient]


def create_options_client(
    settings: Settings,
    client: PortfolioClient,
) -> OptionsClient:
    app = getattr(client, "app", None)
    if app is None:
        return OptionsClient(
            OptionsDailyBarStore(settings.options_database_path),
            historical_provider=UnavailableHistoricalDailyBarProvider(),
            metadata_provider=UnavailableOptionMetadataProvider(),
            chain_provider=UnavailableOptionChainSnapshotProvider(),
            chain_stream_provider=UnavailableOptionChainStreamProvider(),
            historical_stream_provider=UnavailableHistoricalDailyBarStreamProvider(),
        )

    return OptionsClient(
        OptionsDailyBarStore(settings.options_database_path),
        historical_provider=IbHistoricalDailyBarProvider(app),
        metadata_provider=IbOptionMetadataProvider(app),
        chain_provider=IbOptionChainSnapshotProvider(app),
        chain_stream_provider=IbOptionChainStreamProvider(app),
        historical_stream_provider=IbHistoricalDailyBarStreamProvider(app),
        chain_context_workers=settings.option_chain_context_workers,
        max_chain_stream_strikes=settings.max_option_chain_stream_strikes,
    )


class UnavailableHistoricalDailyBarProvider:
    def fetch_daily_bars(self, ticker, start_date, end_date):
        raise OptionsDataUnavailable(
            "Options historical data provider is not configured."
        )
