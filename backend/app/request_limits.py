from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException, Request


class RequestCapacityExceeded(RuntimeError):
    pass


class RequestLimiter:
    def __init__(self, name: str, max_concurrency: int) -> None:
        self.name = name
        self.max_concurrency = max(1, max_concurrency)
        self.semaphore = threading.BoundedSemaphore(self.max_concurrency)

    @contextmanager
    def slot(self, *, timeout_seconds: float) -> Iterator[None]:
        acquired = self.semaphore.acquire(timeout=max(0, timeout_seconds))
        if not acquired:
            raise RequestCapacityExceeded(
                f"{self.name} capacity is temporarily exhausted."
            )

        try:
            yield
        finally:
            self.semaphore.release()


@contextmanager
def request_limit_slot(request: Request, name: str) -> Iterator[None]:
    try:
        with request.app.state.request_limiters[name].slot(
            timeout_seconds=request.app.state.settings.ib_request_queue_timeout_seconds,
        ):
            yield
    except RequestCapacityExceeded as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
