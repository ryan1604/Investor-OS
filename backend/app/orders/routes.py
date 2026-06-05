from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.dependencies import get_order_service, get_request_limiter
from app.orders.service import OrderServiceUnavailable, OrderServiceValidationError
from app.request_limits import RequestCapacityExceeded
from app.schemas import (
    OrderAmendmentRequest,
    OrderCancellationRequest,
    OrderPreviewResponse,
    OrderPreviewableRequest,
    OrderRecord,
    OrderSubmissionResponse,
)
from app.websockets import send_queue_websocket_updates

router = APIRouter()


@router.post("/orders/preview", response_model=OrderPreviewResponse)
def order_preview(
    request: Request,
    order_request: OrderPreviewableRequest,
) -> OrderPreviewResponse:
    return get_order_service(request).preview(order_request)


@router.post("/orders/transmit", response_model=OrderSubmissionResponse)
def transmit_order(
    request: Request,
    order_request: OrderPreviewableRequest,
) -> OrderSubmissionResponse:
    try:
        with get_request_limiter(request, "order_write").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            return get_order_service(request).submit(order_request)
    except OrderServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except OrderServiceValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/orders", response_model=list[OrderRecord])
def orders_snapshot(request: Request) -> list[OrderRecord]:
    return get_order_service(request).snapshot()


@router.patch("/orders/{order_id}", response_model=OrderSubmissionResponse)
def amend_order(
    request: Request,
    order_id: int,
    amendment: OrderAmendmentRequest,
) -> OrderSubmissionResponse:
    try:
        with get_request_limiter(request, "order_write").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            order = get_order_service(request).amend(order_id, amendment)
    except OrderServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except OrderServiceValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return OrderSubmissionResponse(
        order=order,
        message=f"Updated order {order_id}.",
    )


@router.post("/orders/{order_id}/cancel", response_model=OrderSubmissionResponse)
def cancel_order(
    request: Request,
    order_id: int,
    cancellation: OrderCancellationRequest,
) -> OrderSubmissionResponse:
    try:
        with get_request_limiter(request, "order_write").slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            order = get_order_service(request).cancel(order_id, cancellation)
    except OrderServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except OrderServiceValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return OrderSubmissionResponse(
        order=order,
        message=f"Cancelled order {order_id}.",
    )


@router.websocket("/orders/ws")
async def orders_ws(websocket: WebSocket):
    await websocket.accept()
    service = get_order_service(websocket)
    subscriber = service.subscribe()

    try:
        await send_queue_websocket_updates(websocket, subscriber)
    except WebSocketDisconnect:
        return
    finally:
        service.unsubscribe(subscriber)
