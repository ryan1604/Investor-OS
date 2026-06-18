from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.ib.portfolio import IbPortfolioClient, PortfolioClient
from app.ib.routes import router as ib_router
from app.options.factory import OptionsAnalysisClient, create_options_client
from app.options.routes import router as options_router
from app.options_screeners.manager import OptionsScreenerScanManager
from app.options_screeners.credit_spread import (
    CombinedOptionsScreenerScanService,
    CreditSpreadOptionsScreenerScanService,
)
from app.options_screeners.single_leg import SingleLegOptionsScreenerScanService
from app.options_screeners.routes import router as options_screeners_router
from app.options_screeners.service import (
    OptionsScreenerService,
)
from app.options_screeners.store import OptionsScreenerSettingsStore
from app.options_trade_tracker.routes import router as options_trade_tracker_router
from app.options_trade_tracker.store import OptionsTradeTrackerStore
from app.orders.routes import router as orders_router
from app.orders.service import (
    OrderService,
    OrderServiceUnavailable,
    OrderServiceValidationError,
)
from app.portfolio.chart_values_store import PortfolioChartValuesStore
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


@dataclass(frozen=True)
class AppFactories:
    client: Callable[[Settings], PortfolioClient] = IbPortfolioClient
    options_client: Callable[
        [Settings, PortfolioClient],
        OptionsAnalysisClient,
    ] | None = None
    stock_analysis_store: Callable[[Settings], StockAnalysisStore] | None = None
    portfolio_chart_values_store: Callable[
        [Settings],
        PortfolioChartValuesStore,
    ] | None = None
    options_trade_tracker_store: Callable[
        [Settings],
        OptionsTradeTrackerStore,
    ] | None = None
    options_screener_settings_store: Callable[
        [Settings],
        OptionsScreenerSettingsStore,
    ] | None = None
    options_screener_scan_service: Callable[
        [Settings],
        OptionsScreenerService,
    ] | None = None


def create_app(factories: AppFactories | None = None) -> FastAPI:
    settings = get_settings()
    app_factories = factories or AppFactories()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = app_factories.client(settings)
        app.state.settings = settings
        app.state.ib_client = client
        app.state.options_client = (
            app_factories.options_client(settings, client)
            if app_factories.options_client
            else create_options_client(settings, client)
        )
        setup_stores(
            app,
            settings,
            stock_analysis_store_factory=app_factories.stock_analysis_store,
            portfolio_chart_values_store_factory=(
                app_factories.portfolio_chart_values_store
            ),
            options_trade_tracker_store_factory=(
                app_factories.options_trade_tracker_store
            ),
            options_screener_settings_store_factory=(
                app_factories.options_screener_settings_store
            ),
        )
        setup_options_screener_scan_manager(
            app,
            settings,
            scan_service_factory=app_factories.options_screener_scan_service,
        )
        setup_request_limiters(app, settings)
        setup_order_service(app, settings, client)
        client.start()
        with suppress(OrderServiceUnavailable, OrderServiceValidationError):
            app.state.order_service.reconcile_from_ib()
        setup_portfolio_refresh(app, client)
        app.state.portfolio_refresh_service.start()
        yield
        await app.state.portfolio_refresh_service.stop()
        app.state.options_screener_scan_manager.shutdown()
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
    api.include_router(options_screeners_router)
    api.include_router(options_trade_tracker_router)
    api.include_router(orders_router)
    api.include_router(stock_analysis_router)

    return api


def setup_stores(
    app: FastAPI,
    settings: Settings,
    *,
    stock_analysis_store_factory: Callable[[Settings], StockAnalysisStore]
    | None,
    portfolio_chart_values_store_factory: Callable[
        [Settings],
        PortfolioChartValuesStore,
    ]
    | None,
    options_trade_tracker_store_factory: Callable[
        [Settings],
        OptionsTradeTrackerStore,
    ]
    | None,
    options_screener_settings_store_factory: Callable[
        [Settings],
        OptionsScreenerSettingsStore,
    ]
    | None,
) -> None:
    app.state.stock_analysis_store = (
        stock_analysis_store_factory(settings)
        if stock_analysis_store_factory
        else StockAnalysisStore(settings.stock_analysis_database_path)
    )
    app.state.portfolio_chart_values_store = (
        portfolio_chart_values_store_factory(settings)
        if portfolio_chart_values_store_factory
        else PortfolioChartValuesStore(
            settings.portfolio_chart_values_database_path
        )
    )
    app.state.options_trade_tracker_store = (
        options_trade_tracker_store_factory(settings)
        if options_trade_tracker_store_factory
        else OptionsTradeTrackerStore(
            settings.options_trade_trackers_database_path
        )
    )
    app.state.options_screener_settings_store = (
        options_screener_settings_store_factory(settings)
        if options_screener_settings_store_factory
        else OptionsScreenerSettingsStore(settings.options_screeners_database_path)
    )


def setup_options_screener_scan_manager(
    app: FastAPI,
    settings: Settings,
    *,
    scan_service_factory: Callable[[Settings], OptionsScreenerService] | None,
) -> None:
    scan_service = (
        scan_service_factory(settings)
        if scan_service_factory
        else CombinedOptionsScreenerScanService(
            SingleLegOptionsScreenerScanService(app.state.options_client),
            CreditSpreadOptionsScreenerScanService(app.state.options_client),
        )
    )
    app.state.options_screener_scan_manager = OptionsScreenerScanManager(
        app.state.options_screener_settings_store,
        scan_service,
        max_workers=settings.max_concurrent_options_screener_tickers,
        retention_minutes=settings.options_screener_job_retention_minutes,
        subscriber_queue_size=settings.options_screener_subscriber_queue_size,
    )


def setup_request_limiters(app: FastAPI, settings: Settings) -> None:
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


def setup_order_service(
    app: FastAPI,
    settings: Settings,
    client: PortfolioClient,
) -> None:
    app.state.order_service = OrderService(
        getattr(client, "app", None),
        subscriber_queue_size=settings.order_subscriber_queue_size,
    )
    ib_app = getattr(client, "app", None)
    if ib_app is not None:
        ib_app.add_order_status_listener(
            app.state.order_service.handle_ib_order_status,
        )


def setup_portfolio_refresh(app: FastAPI, client: PortfolioClient) -> None:
    app.state.portfolio_cache = PortfolioSnapshotCache(
        empty_portfolio_response(client.get_status()),
    )
    app.state.portfolio_refresh_service = PortfolioRefreshService(
        app.state.portfolio_cache,
        lambda: get_portfolio_response(client),
        refresh_account_summaries=client.refresh_account_summaries,
    )


app = create_app()
