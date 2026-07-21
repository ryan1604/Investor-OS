from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import (
    EarningsWatchAddTickersRequest,
    EarningsWatchAddTickersResponse,
    EarningsWatchResponse,
    EarningsWatchReviewedRequest,
    EarningsWatchRowResponse,
    EarningsWatchStateResponse,
)

router = APIRouter(prefix="/earnings-watch")


@router.get("", response_model=EarningsWatchResponse)
async def get_earnings_watch(
    request: Request,
    response: Response,
) -> EarningsWatchResponse:
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.earnings_watch_service.state(
        start_due_refresh=True,
    )


@router.post("/tickers", response_model=EarningsWatchAddTickersResponse)
async def add_earnings_watch_tickers(
    request: Request,
    add_request: EarningsWatchAddTickersRequest,
) -> EarningsWatchAddTickersResponse:
    return await request.app.state.earnings_watch_service.add_tickers(
        add_request.tickers,
    )


@router.delete("/tickers/{ticker}", response_model=EarningsWatchRowResponse)
async def remove_earnings_watch_ticker(
    request: Request,
    ticker: str,
) -> EarningsWatchRowResponse:
    try:
        return await request.app.state.earnings_watch_service.remove_ticker(ticker)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Ticker not found.") from error


@router.put(
    "/tickers/{ticker}/reviewed",
    response_model=EarningsWatchRowResponse,
)
async def set_earnings_watch_reviewed(
    request: Request,
    ticker: str,
    reviewed_request: EarningsWatchReviewedRequest,
) -> EarningsWatchRowResponse:
    try:
        return await request.app.state.earnings_watch_service.set_reviewed(
            ticker,
            reviewed_request.reviewed,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Ticker not found.") from error


@router.post("/reviews/clear", response_model=EarningsWatchStateResponse)
async def clear_earnings_watch_reviews(
    request: Request,
) -> EarningsWatchStateResponse:
    return await request.app.state.earnings_watch_service.clear_reviewed()
