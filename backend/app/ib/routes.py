from fastapi import APIRouter, Request

from app.schemas import MarketDataLineUsage

router = APIRouter()


@router.get("/ib/status")
def ib_status(request: Request):
    return request.app.state.ib_client.get_status()


@router.get("/ib/market-data-lines", response_model=MarketDataLineUsage)
def ib_market_data_lines(request: Request):
    """Report the shared market-data line budget. Read-only; sends nothing to IB."""
    return request.app.state.ib_client.get_market_data_lines()
