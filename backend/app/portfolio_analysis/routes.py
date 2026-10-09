import asyncio
from contextlib import suppress

import anyio
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool

from app.http import required_ticker
from app.portfolio_analysis.beta_store import BetaOverride
from app.portfolio_analysis.limits_store import RiskLimit
from app.schemas import (
    BetaOverrideRequest,
    BetaOverrideResponse,
    PortfolioAnalysisHistoryResponse,
    PortfolioAnalysisResponse,
    RiskLimitResponse,
    RiskLimitsRequest,
    RiskLimitsResponse,
)

router = APIRouter()


@router.get("/portfolio/analysis", response_model=PortfolioAnalysisResponse)
async def portfolio_analysis(
    request: Request,
    account: str | None = Query(default=None),
) -> PortfolioAnalysisResponse:
    snapshot = request.app.state.portfolio_cache.get()
    return await asyncio.to_thread(
        request.app.state.portfolio_analysis_service.build,
        snapshot,
        account,
    )


@router.get(
    "/portfolio/analysis/history",
    response_model=PortfolioAnalysisHistoryResponse,
)
def portfolio_analysis_history(
    request: Request,
    account: str = Query(...),
) -> PortfolioAnalysisHistoryResponse:
    account = required_account(account)
    return PortfolioAnalysisHistoryResponse(
        account=account,
        snapshots=request.app.state.risk_snapshot_store.history(account),
    )


@router.websocket("/portfolio/analysis/ws")
async def portfolio_analysis_ws(websocket: WebSocket, account: str | None = None):
    """Stream analysis per portfolio refresh; analysis feeds run while connected.

    Clients switch accounts by sending {"account": "<id>"}.
    """
    await websocket.accept()
    state = websocket.app.state
    client = state.ib_client
    service = state.portfolio_analysis_service
    refresh_service = state.portfolio_refresh_service
    with anyio.CancelScope(shield=True):
        await run_in_threadpool(client.add_analysis_viewer)
    snapshot, updates = refresh_service.subscribe()
    viewer_since = service.now()
    receive_task: asyncio.Task | None = None
    update_task: asyncio.Task | None = None

    async def send(current_snapshot) -> None:
        response = await asyncio.to_thread(
            service.build_for_viewer,
            current_snapshot,
            account,
            viewer_since,
        )
        await websocket.send_json(response.model_dump(mode="json"))

    try:
        await send(snapshot)
        receive_task = asyncio.create_task(websocket.receive_json())
        update_task = asyncio.create_task(updates.get())
        while True:
            done, _pending = await asyncio.wait(
                {receive_task, update_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receive_task in done:
                account_switch = requested_account(receive_task)
                if account_switch is not None:
                    account = account_switch or None
                    snapshot = state.portfolio_cache.get()
                    await send(snapshot)
                receive_task = asyncio.create_task(websocket.receive_json())
            if update_task in done:
                snapshot = update_task.result()
                await send(snapshot)
                update_task = asyncio.create_task(updates.get())
    except WebSocketDisconnect:
        return
    finally:
        refresh_service.unsubscribe(updates)
        # Shielded so the viewer is released even when the connection is cancelled.
        with anyio.CancelScope(shield=True):
            for task in (receive_task, update_task):
                if task is None:
                    continue
                task.cancel()
                with suppress(asyncio.CancelledError, WebSocketDisconnect, ValueError):
                    await task
            await run_in_threadpool(client.remove_analysis_viewer)


@router.get(
    "/portfolio/analysis/beta-overrides",
    response_model=list[BetaOverrideResponse],
)
def list_beta_overrides(request: Request) -> list[BetaOverrideResponse]:
    return [
        beta_override_response(override)
        for override in request.app.state.beta_store.list_overrides()
    ]


@router.put(
    "/portfolio/analysis/beta-overrides/{ticker}",
    response_model=BetaOverrideResponse,
)
def set_beta_override(
    request: Request,
    ticker: str,
    override_request: BetaOverrideRequest,
) -> BetaOverrideResponse:
    override = request.app.state.beta_store.set_override(
        required_ticker(ticker),
        override_request.beta,
    )
    return beta_override_response(override)


@router.delete("/portfolio/analysis/beta-overrides/{ticker}", status_code=204)
def clear_beta_override(request: Request, ticker: str) -> Response:
    if not request.app.state.beta_store.delete_override(required_ticker(ticker)):
        raise HTTPException(status_code=404, detail="Beta override not found.")
    return Response(status_code=204)


@router.get(
    "/portfolio/analysis/limits/{account}",
    response_model=RiskLimitsResponse,
)
def get_risk_limits(request: Request, account: str) -> RiskLimitsResponse:
    account = required_account(account)
    return risk_limits_response(account, request.app.state.risk_limits_store.list_limits(account))


@router.put(
    "/portfolio/analysis/limits/{account}",
    response_model=RiskLimitsResponse,
)
def save_risk_limits(
    request: Request,
    account: str,
    limits_request: RiskLimitsRequest,
) -> RiskLimitsResponse:
    account = required_account(account)
    limits = request.app.state.risk_limits_store.replace_limits(account, limits_request.limits)
    return risk_limits_response(account, limits)


def requested_account(receive_task: asyncio.Task) -> str | None:
    """Return the account a client message asks for; ignore malformed messages."""
    try:
        message = receive_task.result()
    except ValueError:
        return None
    if isinstance(message, dict) and isinstance(message.get("account"), str):
        return message["account"].strip()
    return None


def required_account(account: str) -> str:
    account = account.strip()
    if not account:
        raise HTTPException(status_code=400, detail="Account is required.")
    return account


def risk_limits_response(account: str, limits: list[RiskLimit]) -> RiskLimitsResponse:
    return RiskLimitsResponse(
        account=account,
        limits=[
            RiskLimitResponse(key=limit.key, value=limit.value, updated_at=limit.updated_at)
            for limit in limits
        ],
    )


def beta_override_response(override: BetaOverride) -> BetaOverrideResponse:
    return BetaOverrideResponse(
        ticker=override.ticker,
        beta=override.beta,
        updated_at=override.updated_at,
    )
