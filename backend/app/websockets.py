import asyncio
import queue
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from fastapi import WebSocket


async def send_websocket_iterator(
    websocket: WebSocket,
    iterator,
    stop_event: threading.Event,
) -> None:
    async def next_message() -> Any | None:
        return await asyncio.to_thread(next, iterator, None)

    async def cleanup() -> None:
        stop_event.set()
        if hasattr(iterator, "close"):
            await asyncio.to_thread(iterator.close)

    await send_websocket_updates(websocket, next_message, cleanup=cleanup)


async def wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def send_queue_websocket_updates(
    websocket: WebSocket,
    updates: queue.Queue[Any],
) -> None:
    async def next_message() -> Any | None:
        try:
            return await asyncio.to_thread(updates.get, True, 0.1)
        except queue.Empty:
            return None

    await send_websocket_updates(websocket, next_message, stop_on_none=False)


async def send_websocket_updates(
    websocket: WebSocket,
    next_message: Callable[[], Awaitable[Any | None]],
    *,
    cleanup: Callable[[], Awaitable[None]] | None = None,
    stop_on_none: bool = True,
) -> None:
    disconnect_task = asyncio.create_task(wait_for_websocket_disconnect(websocket))
    next_message_task = None

    try:
        while True:
            next_message_task = asyncio.create_task(next_message())
            done, _pending = await asyncio.wait(
                {disconnect_task, next_message_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                return

            message = next_message_task.result()
            next_message_task = None
            if message is None:
                if stop_on_none:
                    return
                continue
            await websocket.send_json(message.model_dump())
    finally:
        if not disconnect_task.done():
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task
        if next_message_task is not None:
            next_message_task.cancel()
            with suppress(asyncio.CancelledError):
                await next_message_task
        if cleanup is not None:
            await cleanup()
