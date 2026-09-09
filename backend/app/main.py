from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.day_trading_tracker.routes import router as day_trading_tracker_router
from app.day_trading_tracker.store import DayTradingTrackerStore
from app.earnings_watch.provider import (
    AlphaVantageEarningsCalendarClient,
    EarningsCalendarProvider,
)
from app.earnings_watch.routes import router as earnings_watch_router
from app.earnings_watch.service import EarningsWatchService
from app.earnings_watch.store import EarningsWatchStore
from app.ib.portfolio import IbPortfolioClient, PortfolioClient
from app.ib.routes import router as ib_router
from app.options.factory import OptionsAnalysisClient, create_options_client
from app.options.routes import router as options_router
from app.options_screeners.manager import OptionsScreenerScanManager
from app.options_screeners.credit_spread import (
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
from app.orders.store import OrderStore
from app.portfolio.chart_values_store import PortfolioChartValuesStore
from app.portfolio.nav_store import DailyNavStore
from app.portfolio.flex import FlexClient
from app.portfolio.nav_sync import NavSyncService
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
class AppOverrides:
    client: PortfolioClient | None = None
    options_client: OptionsAnalysisClient | None = None
    options_screener_scan_service: OptionsScreenerService | None = None
    earnings_calendar_provider: EarningsCalendarProvider | None = None


def create_app(
    settings: Settings | None = None,
    overrides: AppOverrides | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app_overrides = overrides or AppOverrides()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = app_overrides.client or IbPortfolioClient(app_settings)
        app.state.settings = app_settings
        app.state.ib_client = client
        app.state.options_client = (
            app_overrides.options_client
            or create_options_client(app_settings, client)
        )
        setup_stores(app, app_settings)
        app.state.earnings_calendar_provider = (
            app_overrides.earnings_calendar_provider
            or AlphaVantageEarningsCalendarClient(app_settings.alpha_vantage_api_key)
        )
        app.state.earnings_watch_service = EarningsWatchService(
            app.state.earnings_watch_store,
            app.state.earnings_calendar_provider,
        )
        setup_options_screener_scan_manager(
            app,
            app_settings,
            scan_service=app_overrides.options_screener_scan_service,
        )
        setup_request_limiters(app, app_settings)
        setup_order_service(
            app,
            app_settings,
            client,
        )
        client.start()
        setup_portfolio_refresh(app, client)
        app.state.portfolio_refresh_service.start()
        with suppress(OrderServiceUnavailable, OrderServiceValidationError):
            app.state.order_service.reconcile_from_ib()
        app.state.portfolio_nav_sync = NavSyncService(
            app.state.portfolio_nav_store,
            FlexClient(app_settings.ibkr_flex_token, app_settings.ibkr_flex_query_id)
            if app_settings.ibkr_flex_configured else None,
        )
        app.state.portfolio_nav_sync.start()
        try:
            yield
        finally:
            await app.state.portfolio_nav_sync.stop()
        await app.state.portfolio_refresh_service.stop()
        app.state.options_screener_scan_manager.shutdown()
        if hasattr(app.state.options_client, "shutdown"):
            app.state.options_client.shutdown()
        await app.state.earnings_watch_service.stop()
        await app.state.earnings_calendar_provider.aclose()
        client.stop()

    api = FastAPI(title="Investor OS API", lifespan=lifespan)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api.include_router(ib_router)
    api.include_router(portfolio_router)
    api.include_router(options_router)
    api.include_router(options_screeners_router)
    api.include_router(options_trade_tracker_router)
    api.include_router(day_trading_tracker_router)
    api.include_router(orders_router)
    api.include_router(stock_analysis_router)
    api.include_router(earnings_watch_router)

    return api


def setup_stores(
    app: FastAPI,
    settings: Settings,
) -> None:
    app.state.stock_analysis_store = StockAnalysisStore(
        settings.stock_analysis_database_path,
    )
    app.state.portfolio_chart_values_store = PortfolioChartValuesStore(
        settings.portfolio_chart_values_database_path,
    )
    app.state.portfolio_nav_store = DailyNavStore(
        settings.portfolio_chart_values_database_path,
    )
    app.state.options_trade_tracker_store = OptionsTradeTrackerStore(
        settings.options_trade_trackers_database_path,
    )
    app.state.day_trading_tracker_store = DayTradingTrackerStore(
        settings.day_trading_tracker_database_path,
    )
    app.state.options_screener_settings_store = OptionsScreenerSettingsStore(
        settings.options_screeners_database_path,
    )
    app.state.earnings_watch_store = EarningsWatchStore(
        settings.earnings_watch_database_path,
    )


def setup_options_screener_scan_manager(
    app: FastAPI,
    settings: Settings,
    *,
    scan_service: OptionsScreenerService | None,
) -> None:
    if scan_service is None:
        single_leg_service = SingleLegOptionsScreenerScanService(
            app.state.options_client,
        )
        credit_spread_service = CreditSpreadOptionsScreenerScanService(
            app.state.options_client,
        )
        scan_services = {
            "csp": single_leg_service,
            "cc": single_leg_service,
            "cs": credit_spread_service,
        }
        quote_refresh_service = single_leg_service
        spread_quote_refresh_service = credit_spread_service
    else:
        scan_services = {
            "csp": scan_service,
            "cc": scan_service,
            "cs": scan_service,
        }
        quote_refresh_service = scan_service
        spread_quote_refresh_service = scan_service
    app.state.options_screener_scan_manager = OptionsScreenerScanManager(
        app.state.options_screener_settings_store,
        scan_services,
        quote_refresh_service,
        spread_quote_refresh_service,
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
    order_store = OrderStore(settings.orders_database_path)
    app.state.order_service = OrderService(
        getattr(client, "app", None),
        store=order_store,
        subscriber_queue_size=settings.order_subscriber_queue_size,
    )
    ib_app = getattr(client, "app", None)
    if ib_app is not None:
        ib_app.add_order_status_listener(
            app.state.order_service.handle_ib_order_status,
        )
        ib_app.add_execution_listener(
            app.state.order_service.handle_ib_execution,
        )
        ib_app.add_execution_end_listener(
            app.state.order_service.handle_ib_execution_end,
        )
        ib_app.add_completed_order_listener(
            app.state.order_service.handle_ib_completed_order,
        )
        ib_app.add_completed_orders_end_listener(
            app.state.order_service.handle_ib_completed_orders_end,
        )
        ib_app.add_open_order_end_listener(
            app.state.order_service.handle_ib_open_order_end,
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
