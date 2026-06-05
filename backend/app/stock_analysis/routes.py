from fastapi import APIRouter, HTTPException, Request

from app.dependencies import (
    get_options_client,
    get_request_limiter,
    get_stock_analysis_store,
)
from app.options.client import OptionsDataUnavailable
from app.request_limits import RequestCapacityExceeded
from app.schemas import (
    StockAnalysisCurrentPriceResponse,
    StockAnalysisModelRequest,
    StockAnalysisModelResponse,
    empty_stock_analysis_payload,
)
from app.stock_analysis.store import StockAnalysisModel
from app.tickers import require_ticker

router = APIRouter()


@router.get(
    "/stock-analysis/{ticker}",
    response_model=StockAnalysisModelResponse,
)
def stock_analysis_model(
    request: Request,
    ticker: str,
) -> StockAnalysisModelResponse:
    normalized_ticker = required_ticker(ticker)
    try:
        with get_request_limiter(request, "stock_analysis_read").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            model = get_stock_analysis_store(request).get_model(normalized_ticker)
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return stock_analysis_response(normalized_ticker, model)


@router.get(
    "/stock-analysis/{ticker}/current-price",
    response_model=StockAnalysisCurrentPriceResponse,
)
def stock_analysis_current_price(
    request: Request,
    ticker: str,
) -> StockAnalysisCurrentPriceResponse:
    normalized_ticker = required_ticker(ticker)

    try:
        with get_request_limiter(request, "options_analysis").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            analysis = get_options_client(request).get_analysis(normalized_ticker)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if analysis.underlying_price is None:
        raise HTTPException(
            status_code=404,
            detail=f"Current price is unavailable for {normalized_ticker}.",
        )

    return StockAnalysisCurrentPriceResponse(
        ticker=analysis.ticker,
        current_price=analysis.underlying_price,
    )


@router.put(
    "/stock-analysis/{ticker}",
    response_model=StockAnalysisModelResponse,
)
def upsert_stock_analysis_model(
    request: Request,
    ticker: str,
    model_request: StockAnalysisModelRequest,
) -> StockAnalysisModelResponse:
    normalized_ticker = required_ticker(ticker)
    try:
        with get_request_limiter(request, "stock_analysis_write").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            model = get_stock_analysis_store(request).upsert_model(
                normalized_ticker,
                version=model_request.version,
                payload=model_request.payload,
            )
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return stock_analysis_response(normalized_ticker, model)


def required_ticker(ticker: str) -> str:
    try:
        return require_ticker(ticker)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Ticker is required.") from error


def stock_analysis_response(
    ticker: str,
    model: StockAnalysisModel | None,
) -> StockAnalysisModelResponse:
    if model is None:
        return StockAnalysisModelResponse(
            ticker=ticker,
            payload=empty_stock_analysis_payload(),
        )

    return StockAnalysisModelResponse(
        ticker=model.ticker,
        version=model.version,
        payload=model.payload,
        updated_at=model.updated_at,
    )
