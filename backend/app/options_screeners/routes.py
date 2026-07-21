from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from app.options_screeners.manager import (
    OptionsScreenerJobNotActive,
    OptionsScreenerJobNotFound,
    OptionsScreenerScanConflict,
)
from app.options_screeners.service import OptionsScreenerServiceUnavailable
from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionsScreener,
    OptionsScreenerFilters,
    OptionsScreenerCompletedSnapshot,
    OptionsScreenerQuoteRefreshRequest,
    OptionsScreenerQuoteRefreshResponse,
    OptionsScreenerScanJob,
    OptionsScreenerScanState,
    OptionsScreenerSettingsResponse,
    OptionsScreenerSpreadQuoteRefreshRequest,
    OptionsScreenerSpreadQuoteRefreshResponse,
    OptionsScreenerTickerList,
    OptionsScreenerTickerListRequest,
    OptionsScreenerTickerListResponse,
)
from app.websockets import send_queue_websocket_updates

router = APIRouter(prefix="/options-screeners")


@router.get("/settings", response_model=OptionsScreenerSettingsResponse)
def get_options_screener_settings(
    request: Request,
) -> OptionsScreenerSettingsResponse:
    ticker_lists, filters = (
        request.app.state.options_screener_settings_store.get_settings()
    )
    return OptionsScreenerSettingsResponse(
        ticker_lists=ticker_lists,
        filters=filters,
    )


@router.put(
    "/settings/ticker-lists/{list_name}",
    response_model=OptionsScreenerTickerListResponse,
)
def replace_options_screener_ticker_list(
    request: Request,
    list_name: OptionsScreenerTickerList,
    ticker_list_request: OptionsScreenerTickerListRequest,
) -> OptionsScreenerTickerListResponse:
    try:
        tickers = request.app.state.options_screener_settings_store.replace_ticker_list(
            list_name,
            ticker_list_request.tickers,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return OptionsScreenerTickerListResponse(
        list_name=list_name,
        tickers=tickers,
    )


@router.put("/settings/filters/csp", response_model=OptionsScreenerFilters)
def save_csp_filters(
    request: Request,
    filters: OptionsScreenerFilters,
) -> OptionsScreenerFilters:
    return save_screener_filters(request, "csp", filters)


@router.put("/settings/filters/cc", response_model=OptionsScreenerFilters)
def save_cc_filters(
    request: Request,
    filters: OptionsScreenerFilters,
) -> OptionsScreenerFilters:
    return save_screener_filters(request, "cc", filters)


@router.put("/settings/filters/cs", response_model=CreditSpreadScreenerFilters)
def save_cs_filters(
    request: Request,
    filters: CreditSpreadScreenerFilters,
) -> CreditSpreadScreenerFilters:
    return save_screener_filters(request, "cs", filters)


@router.get("/state", response_model=OptionsScreenerScanState)
def get_options_screener_scan_state(
    request: Request,
) -> OptionsScreenerScanState:
    return request.app.state.options_screener_scan_manager.state()


@router.get("/jobs/{job_id}", response_model=OptionsScreenerScanJob)
def get_options_screener_job(
    request: Request,
    job_id: str,
) -> OptionsScreenerScanJob:
    try:
        return request.app.state.options_screener_scan_manager.get_job(job_id)
    except OptionsScreenerJobNotFound as error:
        raise HTTPException(status_code=404, detail="Scan job not found.") from error


@router.get(
    "/snapshots/{screener}",
    response_model=OptionsScreenerCompletedSnapshot | None,
)
def get_options_screener_completed_snapshot(
    request: Request,
    screener: OptionsScreener,
) -> OptionsScreenerCompletedSnapshot | None:
    return request.app.state.options_screener_scan_manager.completed_snapshot(screener)


@router.post("/scans/{screener}", response_model=OptionsScreenerScanJob)
def start_options_screener_scan(
    request: Request,
    screener: OptionsScreener,
) -> OptionsScreenerScanJob:
    try:
        return request.app.state.options_screener_scan_manager.start(screener)
    except OptionsScreenerScanConflict as error:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(error),
                "active_job_id": error.job.id,
                "active_screener": error.job.screener,
            },
        ) from error


@router.post(
    "/scans/{job_id}/cancel",
    response_model=OptionsScreenerScanJob,
)
def cancel_options_screener_scan(
    request: Request,
    job_id: str,
) -> OptionsScreenerScanJob:
    try:
        return request.app.state.options_screener_scan_manager.cancel(job_id)
    except OptionsScreenerJobNotFound as error:
        raise HTTPException(status_code=404, detail="Scan job not found.") from error
    except OptionsScreenerJobNotActive as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/quotes/refresh",
    response_model=OptionsScreenerQuoteRefreshResponse,
)
def refresh_options_screener_quote(
    request: Request,
    quote_request: OptionsScreenerQuoteRefreshRequest,
) -> OptionsScreenerQuoteRefreshResponse:
    try:
        return request.app.state.options_screener_scan_manager.refresh_quote(
            quote_request
        )
    except OptionsScreenerServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post(
    "/quotes/refresh-spread",
    response_model=OptionsScreenerSpreadQuoteRefreshResponse,
)
def refresh_options_screener_spread_quote(
    request: Request,
    quote_request: OptionsScreenerSpreadQuoteRefreshRequest,
) -> OptionsScreenerSpreadQuoteRefreshResponse:
    try:
        return request.app.state.options_screener_scan_manager.refresh_spread_quote(
            quote_request
        )
    except OptionsScreenerServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.websocket("/scans/ws")
async def options_screener_scans_ws(websocket: WebSocket):
    await websocket.accept()
    manager = websocket.app.state.options_screener_scan_manager
    subscriber = manager.subscribe()
    try:
        await send_queue_websocket_updates(websocket, subscriber)
    except WebSocketDisconnect:
        return
    finally:
        manager.unsubscribe(subscriber)


def save_screener_filters(
    request: Request,
    screener: OptionsScreener,
    filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
) -> OptionsScreenerFilters | CreditSpreadScreenerFilters:
    return request.app.state.options_screener_settings_store.save_filters(
        screener,
        filters,
    )
