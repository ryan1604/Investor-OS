from fastapi import APIRouter, HTTPException, Request

from app.options.client import OptionsDataUnavailable
from app.request_limits import RequestCapacityExceeded, request_limit_slot
from app.schemas import (
    StockAnalysisCurrentPriceResponse,
    StockAnalysisModelRequest,
    StockAnalysisModelResponse,
    StockAnalysisPriceRefreshResponse,
    StockAnalysisPriceRefreshResult,
    empty_stock_analysis_payload,
)
from app.stock_analysis.store import StockAnalysisModel
from app.tickers import require_ticker

router = APIRouter()


@router.get(
    "/stock-analysis",
    response_model=list[StockAnalysisModelResponse],
)
def stock_analysis_models(request: Request) -> list[StockAnalysisModelResponse]:
    with request_limit_slot(request, "stock_analysis_read"):
        models = request.app.state.stock_analysis_store.list_models()

    return [stock_analysis_response(model.ticker, model) for model in models]


@router.post(
    "/stock-analysis/current-prices/refresh",
    response_model=StockAnalysisPriceRefreshResponse,
)
def refresh_stock_analysis_current_prices(
    request: Request,
) -> StockAnalysisPriceRefreshResponse:
    with request_limit_slot(request, "stock_analysis_read"):
        models = request.app.state.stock_analysis_store.list_models()

    results = [
        refresh_stock_analysis_current_price(request, model)
        for model in models
    ]
    return StockAnalysisPriceRefreshResponse(results=results)


@router.get(
    "/stock-analysis/{ticker}",
    response_model=StockAnalysisModelResponse,
)
def stock_analysis_model(
    request: Request,
    ticker: str,
) -> StockAnalysisModelResponse:
    normalized_ticker = required_ticker(ticker)
    with request_limit_slot(request, "stock_analysis_read"):
        model = request.app.state.stock_analysis_store.get_model(normalized_ticker)
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
        with request_limit_slot(request, "options_analysis"):
            current_price = request.app.state.options_client.get_underlying_price(
                normalized_ticker
            )
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    with request_limit_slot(request, "stock_analysis_write"):
        request.app.state.stock_analysis_store.update_current_price(
            normalized_ticker,
            current_price,
        )

    return StockAnalysisCurrentPriceResponse(
        ticker=normalized_ticker,
        current_price=current_price,
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
    with request_limit_slot(request, "stock_analysis_write"):
        model = request.app.state.stock_analysis_store.upsert_model(
            normalized_ticker,
            version=model_request.version,
            payload=model_request.payload,
        )
    return stock_analysis_response(normalized_ticker, model)


@router.delete("/stock-analysis/{ticker}", status_code=204)
def delete_stock_analysis_model(request: Request, ticker: str) -> None:
    normalized_ticker = required_ticker(ticker)
    with request_limit_slot(request, "stock_analysis_write"):
        request.app.state.stock_analysis_store.delete_model(normalized_ticker)


def refresh_stock_analysis_current_price(
    request: Request,
    model: StockAnalysisModel,
) -> StockAnalysisPriceRefreshResult:
    try:
        with request.app.state.request_limiters["options_analysis"].slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            current_price = request.app.state.options_client.get_underlying_price(
                model.ticker
            )
    except OptionsDataUnavailable as error:
        return unavailable_price_refresh_result(model, str(error))
    except RequestCapacityExceeded as error:
        return StockAnalysisPriceRefreshResult(
            ticker=model.ticker,
            status="failed",
            current_price=model.current_price,
            message=str(error),
        )

    try:
        with request.app.state.request_limiters["stock_analysis_write"].slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            updated_model = request.app.state.stock_analysis_store.update_current_price(
                model.ticker,
                current_price,
            )
    except RequestCapacityExceeded as error:
        return StockAnalysisPriceRefreshResult(
            ticker=model.ticker,
            status="failed",
            current_price=model.current_price,
            message=str(error),
        )

    return StockAnalysisPriceRefreshResult(
        ticker=updated_model.ticker,
        status="refreshed",
        current_price=updated_model.current_price,
    )


def unavailable_price_refresh_result(
    model: StockAnalysisModel,
    message: str,
) -> StockAnalysisPriceRefreshResult:
    return StockAnalysisPriceRefreshResult(
        ticker=model.ticker,
        status="stale" if model.current_price is not None else "missing",
        current_price=model.current_price,
        message=message,
    )


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
        current_price=model.current_price,
        payload=model.payload,
        updated_at=model.updated_at,
    )
