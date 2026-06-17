import asyncio
import queue
import threading
from contextlib import suppress
from typing import Any

from fastapi import WebSocket


async def send_websocket_iterator(
    websocket: WebSocket,
    iterator,
    stop_event: threading.Event,
) -> None:
    disconnect_task = asyncio.create_task(wait_for_websocket_disconnect(websocket))
    next_message_task = None

    try:
        while True:
            next_message_task = asyncio.create_task(
                asyncio.to_thread(next, iterator, None)
            )
            done, _pending = await asyncio.wait(
                {disconnect_task, next_message_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                return

            message = next_message_task.result()
            next_message_task = None
            if message is None:
                return

            await websocket.send_json(message.model_dump())
    finally:
        stop_event.set()
        if not disconnect_task.done():
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task
        if next_message_task is not None:
            with suppress(Exception):
                await next_message_task
        if hasattr(iterator, "close"):
            await asyncio.to_thread(iterator.close)


async def wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def send_queue_websocket_updates(
    websocket: WebSocket,
    updates: queue.Queue[Any],
) -> None:
    disconnect_task = asyncio.create_task(wait_for_websocket_disconnect(websocket))
    next_message_task = None

    try:
        while True:
            next_message_task = asyncio.create_task(
                asyncio.to_thread(updates.get, True, 0.1),
            )
            done, _pending = await asyncio.wait(
                {disconnect_task, next_message_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                return

            try:
                message = next_message_task.result()
            except queue.Empty:
                next_message_task = None
                continue
            next_message_task = None
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
