from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from app.dependencies import (
    get_portfolio_cache,
    get_portfolio_chart_values_store,
    get_portfolio_refresh_service,
)
from app.portfolio.chart_values_store import PortfolioChartValue
from app.schemas import (
    PortfolioChartValueResponse,
    PortfolioChartValuesRequest,
    PortfolioChartValuesResponse,
    PortfolioResponse,
    normalize_required_account,
)

router = APIRouter()


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio(request: Request) -> PortfolioResponse:
    return get_portfolio_cache(request).get()


@router.get("/portfolio/chart-values", response_model=PortfolioChartValuesResponse)
def portfolio_chart_values(
    request: Request,
    account: str = Query(...),
) -> PortfolioChartValuesResponse:
    normalized_account = required_account(account)
    rows = get_portfolio_chart_values_store(request).list_values(normalized_account)
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
            portfolio_value=row.portfolio_value,
            amount_invested=row.amount_invested,
            updated_at="",
        )
        for row in chart_values_request.rows
    ]
    rows = get_portfolio_chart_values_store(request).replace_values(
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
    service = get_portfolio_refresh_service(websocket)
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
        portfolio_value=value.portfolio_value,
        amount_invested=value.amount_invested,
        updated_at=value.updated_at,
    )
