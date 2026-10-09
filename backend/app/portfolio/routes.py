from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.portfolio.chart_values_store import PortfolioChartValue
from app.portfolio.nav_store import DailyNavResponse
from app.schemas import (
    PortfolioChartValueResponse,
    PortfolioChartValuesRequest,
    PortfolioChartValuesResponse,
    PortfolioResponse,
    normalize_required_account,
)

router = APIRouter()


@router.get("/portfolio/nav/accounts", response_model=list[str])
def portfolio_nav_accounts(request: Request) -> list[str]:
    return request.app.state.portfolio_nav_store.list_accounts()


@router.get("/portfolio/nav", response_model=DailyNavResponse)
def portfolio_nav(request: Request, account: str = Query(...)) -> DailyNavResponse:
    result = request.app.state.portfolio_nav_store.history(
        required_account(account),
        configured=request.app.state.settings.ibkr_flex_configured,
    )
    return request.app.state.portfolio_nav_sync.update_status(result)


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio(request: Request) -> PortfolioResponse:
    return request.app.state.portfolio_cache.get()


@router.get("/portfolio/chart-values", response_model=PortfolioChartValuesResponse)
def portfolio_chart_values(
    request: Request,
    account: str = Query(...),
) -> PortfolioChartValuesResponse:
    normalized_account = required_account(account)
    rows = request.app.state.portfolio_chart_values_store.list_values(
        normalized_account,
    )
    return PortfolioChartValuesResponse(
        account=normalized_account,
        rows=[portfolio_chart_value_response(row) for row in rows],
    )


@router.put("/portfolio/chart-values", response_model=PortfolioChartValuesResponse)
def replace_portfolio_chart_values(
    request: Request,
    chart_values_request: PortfolioChartValuesRequest,
    account: str = Query(...),
) -> PortfolioChartValuesResponse:
    normalized_account = required_account(account)
    values = [
        PortfolioChartValue(
            account=normalized_account,
            month=row.month,
            amount_invested=row.amount_invested,
            updated_at="",
        )
        for row in chart_values_request.rows
    ]
    rows = request.app.state.portfolio_chart_values_store.replace_values(
        normalized_account,
        values,
    )
    return PortfolioChartValuesResponse(
        account=normalized_account,
        rows=[portfolio_chart_value_response(row) for row in rows],
    )


@router.websocket("/portfolio/ws")
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


@router.websocket("/portfolio/quotes/ws")
async def portfolio_quotes_ws(websocket: WebSocket):
    """Keep position quote lines subscribed only while a Portfolio page is open."""
    await websocket.accept()
    client = websocket.app.state.ib_client
    await run_in_threadpool(client.add_quote_viewer)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
    finally:
        await run_in_threadpool(client.remove_quote_viewer)


def required_account(account: str) -> str:
    try:
        return normalize_required_account(account)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Account is required.") from error


def portfolio_chart_value_response(
    value: PortfolioChartValue,
) -> PortfolioChartValueResponse:
    return PortfolioChartValueResponse(
        month=value.month,
        amount_invested=value.amount_invested,
        updated_at=value.updated_at,
    )
