from fastapi import Request, WebSocket

from app.ib.portfolio import PortfolioClient
from app.options.factory import OptionsAnalysisClient
from app.options_trade_tracker.store import OptionsTradeTrackerStore
from app.orders.service import OrderService
from app.portfolio.chart_values_store import PortfolioChartValuesStore
from app.portfolio.service import PortfolioRefreshService, PortfolioSnapshotCache
from app.request_limits import RequestLimiter
from app.stock_analysis.store import StockAnalysisStore


def get_ib_client(request: Request) -> PortfolioClient:
    return request.app.state.ib_client


def get_options_client(request: Request | WebSocket) -> OptionsAnalysisClient:
    return request.app.state.options_client


def get_order_service(request: Request | WebSocket) -> OrderService:
    return request.app.state.order_service


def get_portfolio_cache(request: Request) -> PortfolioSnapshotCache:
    return request.app.state.portfolio_cache


def get_portfolio_refresh_service(websocket: WebSocket) -> PortfolioRefreshService:
    return websocket.app.state.portfolio_refresh_service


def get_portfolio_chart_values_store(request: Request) -> PortfolioChartValuesStore:
    return request.app.state.portfolio_chart_values_store


def get_options_trade_tracker_store(request: Request) -> OptionsTradeTrackerStore:
    return request.app.state.options_trade_tracker_store


def get_stock_analysis_store(request: Request) -> StockAnalysisStore:
    return request.app.state.stock_analysis_store


def get_request_limiter(request: Request, name: str) -> RequestLimiter:
    return request.app.state.request_limiters[name]
