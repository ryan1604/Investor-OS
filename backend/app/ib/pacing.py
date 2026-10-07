from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from time import monotonic, sleep


class MessagePacer:
    """Keep outgoing IB requests under a strict rolling-window rate.

    IB disconnects clients that exceed 50 messages per second, so every
    request that can be issued in bulk waits here for a free slot.
    """

    def __init__(
        self,
        max_messages: int,
        window_seconds: float = 1.0,
        *,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.max_messages = max(1, max_messages)
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleeper = sleeper
        self.sent: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            while True:
                now = self.clock()
                while self.sent and now - self.sent[0] >= self.window_seconds:
                    self.sent.popleft()
                if len(self.sent) < self.max_messages:
                    self.sent.append(now)
                    return
                self.sleeper(self.window_seconds - (now - self.sent[0]))


class OutstandingRequestLimiter:
    """Cap requests IB has not answered yet across every caller.

    A slot is held until IB answers, even after the caller stops waiting,
    because IB keeps working through abandoned requests. Counting them keeps
    IB's queue short enough that new requests do not time out behind them.

    Background requests, such as preloading chains nobody has opened yet, use
    at most ``background_capacity`` slots and wait while anyone else waits.
    Urgent requests, single lookups such as a ticker's options metadata, take
    the next free slot ahead of bulk lookups that are already waiting.
    """

    def __init__(
        self,
        capacity: int | None,
        *,
        background_capacity: int | None = None,
        max_hold_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.capacity = capacity
        self.background_capacity = background_capacity
        self.max_hold_seconds = max_hold_seconds
        self.clock = clock
        self.held_since: dict[int, float] = {}
        self.background_keys: set[int] = set()
        self.foreground_waiting = 0
        self.urgent_waiting = 0
        self.condition = threading.Condition()

    def acquire(
        self,
        key: int,
        *,
        timeout: float,
        stop_event: threading.Event | None = None,
        is_background: Callable[[], bool] | None = None,
        urgent: bool = False,
    ) -> bool:
        if self.capacity is None:
            return True
        deadline = self.clock() + timeout
        with self.condition:
            waiting_as_foreground = False
            if urgent:
                self.urgent_waiting += 1
            try:
                while True:
                    self._reclaim_stale()
                    # Checked each pass: a background request can be promoted
                    # while it waits, once someone opens the chain it loads.
                    background = is_background is not None and is_background()
                    if background != (not waiting_as_foreground):
                        waiting_as_foreground = not background
                        self.foreground_waiting += 1 if waiting_as_foreground else -1
                    if self._has_free_slot(background, urgent=urgent):
                        self.held_since[key] = self.clock()
                        if background:
                            self.background_keys.add(key)
                        return True
                    remaining = deadline - self.clock()
                    if remaining <= 0 or (
                        stop_event is not None and stop_event.is_set()
                    ):
                        return False
                    self.condition.wait(min(0.1, remaining))
            finally:
                if waiting_as_foreground:
                    self.foreground_waiting -= 1
                if urgent:
                    self.urgent_waiting -= 1

    def release(self, key: int) -> None:
        with self.condition:
            if self.held_since.pop(key, None) is not None:
                self.background_keys.discard(key)
                self.condition.notify_all()

    def clear(self) -> None:
        with self.condition:
            self.held_since.clear()
            self.background_keys.clear()
            self.condition.notify_all()

    def outstanding(self) -> int:
        with self.condition:
            return len(self.held_since)

    def _has_free_slot(self, background: bool, *, urgent: bool) -> bool:
        if len(self.held_since) >= self.capacity:
            return False
        if urgent:
            return True
        if self.urgent_waiting:
            return False
        if not background:
            return True
        return self.foreground_waiting == 0 and (
            self.background_capacity is None
            or len(self.background_keys) < self.background_capacity
        )

    def _reclaim_stale(self) -> None:
        # IB can drop a request without answering, for example across a
        # reconnect; never let one hold a slot forever.
        cutoff = self.clock() - self.max_hold_seconds
        for key in [key for key, since in self.held_since.items() if since <= cutoff]:
            del self.held_since[key]
            self.background_keys.discard(key)


def contract_details_limiter(app) -> OutstandingRequestLimiter:
    """Return the app's shared limiter, or an unlimited one for apps without it."""
    limiter = getattr(app, "contract_details_slots", None)
    if limiter is None:
        limiter = OutstandingRequestLimiter(None)
        try:
            app.contract_details_slots = limiter
        except AttributeError:
            pass
    return limiter
