from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


class RequestCapacityExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class RequestLimiterSnapshot:
    name: str
    max_concurrency: int
    active: int


class RequestLimiter:
    def __init__(self, name: str, max_concurrency: int) -> None:
        self.name = name
        self.max_concurrency = max(1, max_concurrency)
        self.semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self.lock = threading.Lock()
        self.active = 0

    @contextmanager
    def slot(self, *, timeout_seconds: float) -> Iterator[None]:
        acquired = self.semaphore.acquire(timeout=max(0, timeout_seconds))
        if not acquired:
            raise RequestCapacityExceeded(
                f"{self.name} capacity is temporarily exhausted."
            )

        with self.lock:
            self.active += 1

        try:
            yield
        finally:
            with self.lock:
                self.active -= 1
            self.semaphore.release()

    def snapshot(self) -> RequestLimiterSnapshot:
        with self.lock:
            active = self.active

        return RequestLimiterSnapshot(
            name=self.name,
            max_concurrency=self.max_concurrency,
            active=active,
        )
