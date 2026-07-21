import threading

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.options.client import OptionsDataUnavailable
from app.request_limits import request_limit_slot
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
    options_client = request.app.state.options_client
    try:
        with request_limit_slot(request, "options_analysis"):
            return options_client.get_analysis(ticker)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/options/{ticker}/chain", response_model=OptionChainResponse)
def option_chain(
    request: Request,
    ticker: str,
    expiration: str,
) -> OptionChainResponse:
    options_client = request.app.state.options_client
    try:
        with request_limit_slot(request, "option_chain"):
            return options_client.get_chain(ticker, expiration)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/options/{ticker}/expirations",
    response_model=OptionExpirationsResponse,
)
def option_expirations(
    request: Request,
    ticker: str,
) -> OptionExpirationsResponse:
    options_client = request.app.state.options_client
    try:
        return options_client.get_expirations(ticker)
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.websocket("/options/{ticker}/chain/ws")
async def option_chain_ws(websocket: WebSocket, ticker: str, expiration: str):
    await websocket.accept()
    options_client = websocket.app.state.options_client
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
    options_client = websocket.app.state.options_client
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
