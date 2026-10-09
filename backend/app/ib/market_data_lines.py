from __future__ import annotations

import threading
from dataclasses import dataclass
from time import monotonic

# Lower values win. Unmet demand from a group blocks grants to lower-priority groups.
MARKET_DATA_LINE_PRIORITIES = {
    "portfolio": 0,
    "chart": 1,
    "chain": 2,
    "quote_refresh": 3,
    "screener": 4,
}


@dataclass(frozen=True)
class MarketDataLineSnapshot:
    capacity: int
    used: int
    used_by_group: dict[str, int]
    pending_by_group: dict[str, int]


class MarketDataLineBudget:
    """Shared allowance of simultaneous IB market-data lines."""

    def __init__(self, capacity: int) -> None:
        self.capacity = max(0, capacity)
        self.used_by_group: dict[str, int] = {}
        self.pending_by_owner: dict[object, tuple[str, int]] = {}
        self.condition = threading.Condition()

    def try_acquire(
        self,
        group: str,
        count: int,
        *,
        minimum: int = 1,
        owner: object | None = None,
    ) -> int:
        """Grant up to count lines now; record the unmet rest as owner demand."""
        with self.condition:
            granted = self._grant(group, count, minimum)
            if owner is not None:
                self._set_pending(owner, group, count - granted)
            return granted

    def acquire(
        self,
        group: str,
        count: int,
        *,
        minimum: int = 1,
        stop_event: threading.Event | None = None,
        timeout: float | None = None,
    ) -> int:
        """Wait until at least minimum lines are free; return 0 on stop or timeout."""
        if count <= 0:
            return 0
        deadline = None if timeout is None else monotonic() + timeout
        owner = object()
        with self.condition:
            try:
                while True:
                    # Own pending demand has equal priority, so it never blocks this grant.
                    granted = self._grant(group, count, minimum)
                    if granted:
                        return granted
                    self._set_pending(owner, group, count)
                    remaining = (
                        0.05 if deadline is None else min(0.05, deadline - monotonic())
                    )
                    if remaining <= 0 or (stop_event is not None and stop_event.is_set()):
                        return 0
                    self.condition.wait(remaining)
            finally:
                if self.pending_by_owner.pop(owner, None) is not None:
                    self.condition.notify_all()

    def release(self, group: str, count: int) -> None:
        if count <= 0:
            return
        with self.condition:
            self.used_by_group[group] = max(0, self.used_by_group.get(group, 0) - count)
            self.condition.notify_all()

    def clear_pending(self, owner: object) -> None:
        with self.condition:
            if self.pending_by_owner.pop(owner, None) is not None:
                self.condition.notify_all()

    def used(self) -> int:
        with self.condition:
            return sum(self.used_by_group.values())

    def usage_by_group(self) -> dict[str, int]:
        with self.condition:
            return {group: used for group, used in self.used_by_group.items() if used}

    def snapshot(self) -> MarketDataLineSnapshot:
        """Return capacity, lines in use, and waiting demand for every group at one instant."""
        with self.condition:
            used = {group: self.used_by_group.get(group, 0) for group in MARKET_DATA_LINE_PRIORITIES}
            pending = dict.fromkeys(MARKET_DATA_LINE_PRIORITIES, 0)
            for group, count in self.pending_by_owner.values():
                pending[group] += count
            return MarketDataLineSnapshot(
                capacity=self.capacity,
                used=sum(used.values()),
                used_by_group=used,
                pending_by_group=pending,
            )

    def _grant(self, group: str, count: int, minimum: int) -> int:
        granted = min(count, self._available(group))
        if granted <= 0 or granted < min(max(1, minimum), count):
            return 0
        self.used_by_group[group] = self.used_by_group.get(group, 0) + granted
        return granted

    def _available(self, group: str) -> int:
        priority = MARKET_DATA_LINE_PRIORITIES[group]
        blocked = sum(
            pending
            for pending_group, pending in self.pending_by_owner.values()
            if MARKET_DATA_LINE_PRIORITIES[pending_group] < priority
        )
        return self.capacity - sum(self.used_by_group.values()) - blocked

    def _set_pending(self, owner: object, group: str, count: int) -> None:
        current = self.pending_by_owner.get(owner)
        if count > 0:
            self.pending_by_owner[owner] = (group, count)
        else:
            self.pending_by_owner.pop(owner, None)
        if self.pending_by_owner.get(owner) != current:
            self.condition.notify_all()


def market_data_line_budget(app) -> MarketDataLineBudget:
    """Return the app's shared market-data budget."""
    return app.market_data_lines
