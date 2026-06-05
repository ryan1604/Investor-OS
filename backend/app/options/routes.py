import threading

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.dependencies import get_options_client, get_request_limiter
from app.options.client import OptionsDataUnavailable
from app.request_limits import RequestCapacityExceeded
from app.schemas import (
    OptionChainLiveMessage,
    OptionChainResponse,
    OptionExpirationsResponse,
    OptionsAnalysisResponse,
)
from app.websockets import send_websocket_iterator

router = APIRouter()


@router.get("/options/{ticker}/analysis", response_model=OptionsAnalysisResponse)
def options_analysis(request: Request, ticker: str) -> OptionsAnalysisResponse:
    options_client = get_options_client(request)
    try:
        with get_request_limiter(request, "options_analysis").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            return options_client.get_analysis(ticker)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/options/{ticker}/chain", response_model=OptionChainResponse)
def option_chain(
    request: Request,
    ticker: str,
    expiration: str,
) -> OptionChainResponse:
    options_client = get_options_client(request)
    try:
        with get_request_limiter(request, "option_chain").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            return options_client.get_chain(ticker, expiration)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get(
    "/options/{ticker}/expirations",
    response_model=OptionExpirationsResponse,
)
def option_expirations(
    request: Request,
    ticker: str,
) -> OptionExpirationsResponse:
    options_client = get_options_client(request)
    try:
        return options_client.get_expirations(ticker)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.websocket("/options/{ticker}/chain/ws")
async def option_chain_ws(websocket: WebSocket, ticker: str, expiration: str):
    await websocket.accept()
    options_client = get_options_client(websocket)
    stop_event = threading.Event()
    iterator = None

    try:
        iterator = iter(
            options_client.stream_chain(
                ticker,
                expiration,
                stop_event=stop_event,
            )
        )
        await send_websocket_iterator(websocket, iterator, stop_event)
    except OptionsDataUnavailable as error:
        message = OptionChainLiveMessage(
            type="snapshot",
            ticker=ticker.upper(),
            expiration=expiration,
            rows=[],
            message=str(error),
        )
        await websocket.send_json(message.model_dump())
    except WebSocketDisconnect:
        return


@router.websocket("/options/{ticker}/chart/ws")
async def options_chart_ws(websocket: WebSocket, ticker: str):
    await websocket.accept()
    options_client = get_options_client(websocket)
    stop_event = threading.Event()
    iterator = None

    try:
        iterator = iter(
            options_client.stream_chart(
                ticker,
                stop_event=stop_event,
            )
        )
        await send_websocket_iterator(websocket, iterator, stop_event)
    except OptionsDataUnavailable:
        return
    except WebSocketDisconnect:
        return
