from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.http import service_errors_as_http
from app.request_limits import request_limit_slot
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
    return request.app.state.order_service.preview(order_request)


@router.post("/orders/transmit", response_model=OrderSubmissionResponse)
def transmit_order(
    request: Request,
    order_request: OrderPreviewableRequest,
) -> OrderSubmissionResponse:
    with service_errors_as_http():
        with request_limit_slot(request, "order_write"):
            return request.app.state.order_service.submit(order_request)


@router.get("/orders", response_model=list[OrderRecord])
def orders_snapshot(request: Request) -> list[OrderRecord]:
    return request.app.state.order_service.snapshot()


@router.post("/orders/reconcile")
def reconcile_orders(request: Request) -> dict[str, str]:
    with service_errors_as_http():
        request.app.state.order_service.reconcile_from_ib()
    return {"message": "Requested IB open-order reconciliation."}


@router.patch("/orders/{order_id}", response_model=OrderSubmissionResponse)
def amend_order(
    request: Request,
    order_id: int,
    amendment: OrderAmendmentRequest,
) -> OrderSubmissionResponse:
    with service_errors_as_http():
        with request_limit_slot(request, "order_write"):
            order = request.app.state.order_service.amend(order_id, amendment)

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
    with service_errors_as_http():
        with request_limit_slot(request, "order_write"):
            order = request.app.state.order_service.cancel(order_id, cancellation)

    return OrderSubmissionResponse(
        order=order,
        message=f"Cancelled order {order_id}.",
    )


@router.websocket("/orders/ws")
async def orders_ws(websocket: WebSocket):
    await websocket.accept()
    service = websocket.app.state.order_service
    subscriber = service.subscribe()

    try:
        await send_queue_websocket_updates(websocket, subscriber)
    except WebSocketDisconnect:
        return
    finally:
        service.unsubscribe(subscriber)
