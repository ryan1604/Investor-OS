from collections.abc import Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.ib.portfolio import IbPortfolioClient, PortfolioClient
from app.ib.routes import router as ib_router
from app.options.factory import OptionsAnalysisClient, create_options_client
from app.options.routes import router as options_router
from app.orders.routes import router as orders_router
from app.orders.service import (
    OrderService,
    OrderServiceUnavailable,
    OrderServiceValidationError,
)
from app.portfolio.routes import router as portfolio_router
from app.portfolio.service import (
    PortfolioRefreshService,
    PortfolioSnapshotCache,
    empty_portfolio_response,
    get_portfolio_response,
)
from app.request_limits import RequestLimiter
from app.stock_analysis.routes import router as stock_analysis_router
from app.stock_analysis.store import StockAnalysisStore


def create_app(
    client_factory: Callable[[Settings], PortfolioClient] = IbPortfolioClient,
    options_client_factory: Callable[
        [Settings, PortfolioClient],
        OptionsAnalysisClient,
    ]
    | None = None,
    stock_analysis_store_factory: Callable[[Settings], StockAnalysisStore]
    | None = None,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = client_factory(settings)
        app.state.settings = settings
        app.state.ib_client = client
        app.state.options_client = (
            options_client_factory(settings, client)
            if options_client_factory
            else create_options_client(settings, client)
        )
        app.state.stock_analysis_store = (
            stock_analysis_store_factory(settings)
            if stock_analysis_store_factory
            else StockAnalysisStore(settings.stock_analysis_database_path)
        )
        app.state.request_limiters = {
            "options_analysis": RequestLimiter(
                "options analysis",
                settings.max_concurrent_options_analysis,
            ),
            "option_chain": RequestLimiter(
                "option chain",
                settings.max_concurrent_option_chains,
            ),
            "order_write": RequestLimiter(
                "order write",
                settings.max_concurrent_order_writes,
            ),
            "stock_analysis_read": RequestLimiter(
                "stock-analysis read",
                settings.max_concurrent_stock_analysis_reads,
            ),
            "stock_analysis_write": RequestLimiter(
                "stock-analysis write",
                settings.max_concurrent_stock_analysis_writes,
            ),
        }
        app.state.order_service = OrderService(
            getattr(client, "app", None),
            subscriber_queue_size=settings.order_subscriber_queue_size,
        )
        ib_app = getattr(client, "app", None)
        if ib_app is not None:
            ib_app.add_order_status_listener(
                app.state.order_service.handle_ib_order_status,
            )
        client.start()
        with suppress(OrderServiceUnavailable, OrderServiceValidationError):
            app.state.order_service.reconcile_from_ib()
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
        if hasattr(app.state.options_client, "shutdown"):
            app.state.options_client.shutdown()
        client.stop()

    api = FastAPI(title="Investor OS API", lifespan=lifespan)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api.include_router(ib_router)
    api.include_router(portfolio_router)
    api.include_router(options_router)
    api.include_router(orders_router)
    api.include_router(stock_analysis_router)

    return api


app = create_app()
