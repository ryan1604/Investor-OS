import asyncio
import logging
import threading
from time import perf_counter
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.ib.options import (
    IbHistoricalDailyBarProvider,
    IbHistoricalDailyBarStreamProvider,
    IbOptionChainSnapshotProvider,
    IbOptionChainStreamProvider,
    IbOptionMetadataProvider,
)
from app.ib.portfolio import IbPortfolioClient, PortfolioClient
from app.options.client import (
    OptionsClient,
    OptionsDataUnavailable,
    UnavailableOptionChainSnapshotProvider,
    UnavailableOptionChainStreamProvider,
    UnavailableHistoricalDailyBarStreamProvider,
    UnavailableOptionMetadataProvider,
)
from app.options.store import OptionsDailyBarStore
from app.portfolio.domain import attach_account_summaries
from app.portfolio.service import PortfolioRefreshService, PortfolioSnapshotCache
from app.schemas import (
    IbStatus,
    OptionChainLiveMessage,
    OptionChainResponse,
    OptionExpirationsResponse,
    OptionsAnalysisResponse,
    PortfolioResponse,
)

logger = logging.getLogger(__name__)


class OptionsAnalysisClient(Protocol):
    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
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


def create_app(
    client_factory: Callable[[Settings], PortfolioClient] = IbPortfolioClient,
    options_client_factory: Callable[
        [Settings, PortfolioClient],
        OptionsAnalysisClient,
    ]
    | None = None,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = client_factory(settings)
        app.state.ib_client = client
        app.state.options_client = (
            options_client_factory(settings, client)
            if options_client_factory
            else create_options_client(settings, client)
        )
        client.start()
        app.state.portfolio_cache = PortfolioSnapshotCache(
            empty_portfolio_response(client.get_status()),
        )
        app.state.portfolio_refresh_service = PortfolioRefreshService(
            app.state.portfolio_cache,
            lambda: get_portfolio_response(client),
            refresh_account_summaries=client.refresh_account_summaries,
        )
        app.state.portfolio_refresh_service.start()
        yield
        await app.state.portfolio_refresh_service.stop()
        client.stop()

    api = FastAPI(title="Investor OS API", lifespan=lifespan)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/ib/status")
    def ib_status(request: Request):
        return get_ib_client(request).get_status()

    @api.get("/portfolio", response_model=PortfolioResponse)
    def portfolio(request: Request) -> PortfolioResponse:
        return get_portfolio_cache(request).get()

    @api.get("/options/{ticker}/analysis", response_model=OptionsAnalysisResponse)
    def options_analysis(request: Request, ticker: str) -> OptionsAnalysisResponse:
        options_client = get_options_client(request)
        try:
            return options_client.get_analysis(ticker)
        except OptionsDataUnavailable as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/options/{ticker}/chain", response_model=OptionChainResponse)
    def option_chain(
        request: Request,
        ticker: str,
        expiration: str,
    ) -> OptionChainResponse:
        options_client = get_options_client(request)
        try:
            return options_client.get_chain(ticker, expiration)
        except OptionsDataUnavailable as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get(
        "/options/{ticker}/expirations",
        response_model=OptionExpirationsResponse,
    )
    def option_expirations(
        request: Request,
        ticker: str,
    ) -> OptionExpirationsResponse:
        options_client = get_options_client(request)
        try:
            return options_client.get_expirations(ticker)
        except OptionsDataUnavailable as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.websocket("/portfolio/ws")
    async def portfolio_ws(websocket: WebSocket):
        await websocket.accept()
        service = websocket.app.state.portfolio_refresh_service
        snapshot, queue = service.subscribe()

        try:
            await websocket.send_json(snapshot.model_dump())

            while True:
                snapshot = await queue.get()
                await websocket.send_json(snapshot.model_dump())
        except WebSocketDisconnect:
            return
        finally:
            service.unsubscribe(queue)

    @api.websocket("/options/{ticker}/chain/ws")
    async def option_chain_ws(websocket: WebSocket, ticker: str, expiration: str):
        await websocket.accept()
        options_client = get_options_client(websocket)
        stop_event = threading.Event()
        iterator = None

        try:
            iterator = iter(
                options_client.stream_chain(
                    ticker,
                    expiration,
                    stop_event=stop_event,
                )
            )
            await send_websocket_iterator(websocket, iterator, stop_event)
        except OptionsDataUnavailable as error:
            message = OptionChainLiveMessage(
                type="snapshot",
                ticker=ticker.upper(),
                expiration=expiration,
                rows=[],
                message=str(error),
            )
            await websocket.send_json(message.model_dump())
        except WebSocketDisconnect:
            return

    @api.websocket("/options/{ticker}/chart/ws")
    async def options_chart_ws(websocket: WebSocket, ticker: str):
        await websocket.accept()
        options_client = get_options_client(websocket)
        stop_event = threading.Event()
        iterator = None

        try:
            iterator = iter(
                options_client.stream_chart(
                    ticker,
                    stop_event=stop_event,
                )
            )
            await send_websocket_iterator(websocket, iterator, stop_event)
        except OptionsDataUnavailable:
            return
        except WebSocketDisconnect:
            return

    return api


async def send_websocket_iterator(
    websocket: WebSocket,
    iterator,
    stop_event: threading.Event,
) -> None:
    disconnect_task = asyncio.create_task(wait_for_websocket_disconnect(websocket))
    next_message_task = None

    try:
        while True:
            next_message_task = asyncio.create_task(
                asyncio.to_thread(next, iterator, None)
            )
            done, _pending = await asyncio.wait(
                {disconnect_task, next_message_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                return

            message = next_message_task.result()
            next_message_task = None
            if message is None:
                return

            await websocket.send_json(message.model_dump())
    finally:
        stop_event.set()
        if not disconnect_task.done():
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task
        if next_message_task is not None:
            with suppress(Exception):
                await next_message_task
        if hasattr(iterator, "close"):
            await asyncio.to_thread(iterator.close)


async def wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


def get_ib_client(request: Request) -> PortfolioClient:
    return request.app.state.ib_client


def get_options_client(request: Request) -> OptionsAnalysisClient:
    return request.app.state.options_client


def get_portfolio_cache(request: Request) -> PortfolioSnapshotCache:
    return request.app.state.portfolio_cache


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
    )


class UnavailableHistoricalDailyBarProvider:
    def fetch_daily_bars(self, ticker, start_date, end_date):
        raise OptionsDataUnavailable(
            "Options historical data provider is not configured."
        )


def get_portfolio_response(client: PortfolioClient) -> PortfolioResponse:
    started_at = perf_counter()
    status: IbStatus = client.get_status()

    if not status.connected:
        return empty_portfolio_response(status)

    positions = client.get_positions()
    accounts = client.get_account_summaries(positions)
    positions = attach_account_summaries(positions, accounts)
    logger.info(
        "Portfolio snapshot refreshed accounts=%s positions=%s total_ms=%.1f",
        len(accounts),
        len(positions),
        (perf_counter() - started_at) * 1_000,
    )
    return PortfolioResponse(
        status=status,
        accounts=accounts,
        positions=positions,
        message=f"Loaded {len(positions)} position(s) from Interactive Brokers.",
    )


def empty_portfolio_response(status: IbStatus) -> PortfolioResponse:
    return PortfolioResponse(
        status=status,
        accounts=[],
        positions=[],
        message=(
            "Portfolio data has not loaded yet."
            if status.connected
            else "Interactive Brokers is not connected."
        ),
    )


app = create_app()
