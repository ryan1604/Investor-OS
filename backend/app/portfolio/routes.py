from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.dependencies import get_portfolio_cache, get_portfolio_refresh_service
from app.schemas import PortfolioResponse

router = APIRouter()


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio(request: Request) -> PortfolioResponse:
    return get_portfolio_cache(request).get()


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
