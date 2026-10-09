import threading

from ibapi.contract import Contract

from app.ib.app import IbPortfolioApp
from app.ib.pacing import MessagePacer, OutstandingRequestLimiter
from tests.conftest import wait_until


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_message_pacer_waits_for_the_rolling_window():
    clock = FakeClock()
    pacer = MessagePacer(2, 1.0, clock=clock, sleeper=clock.sleep)

    pacer.wait()
    clock.now = 0.4
    pacer.wait()
    pacer.wait()

    assert clock.sleeps == [0.6]
    assert clock.now == 1.0

    clock.now = 1.5
    pacer.wait()

    assert clock.sleeps == [0.6]


class CountingPacer:
    def __init__(self) -> None:
        self.waits = 0

    def wait(self) -> None:
        self.waits += 1


def test_ib_app_paces_contract_and_market_data_requests():
    app = IbPortfolioApp()
    pacer = CountingPacer()
    app.message_pacer = pacer

    app.reqContractDetails(1, Contract())
    app.reqMktData(2, Contract(), "", False, False, [])
    app.cancelMktData(2)

    assert pacer.waits == 3


def test_outstanding_limiter_waits_for_a_released_slot():
    limiter = OutstandingRequestLimiter(1)
    assert limiter.acquire(1, timeout=1)
    threading.Timer(0.05, limiter.release, args=(1,)).start()

    assert limiter.acquire(2, timeout=2)
    assert limiter.outstanding() == 1


def test_outstanding_limiter_gives_up_at_the_timeout_or_stop():
    limiter = OutstandingRequestLimiter(1)
    stop_event = threading.Event()
    stop_event.set()
    limiter.acquire(1, timeout=1)

    assert not limiter.acquire(2, timeout=0.05)
    assert not limiter.acquire(3, timeout=5, stop_event=stop_event)
    assert limiter.outstanding() == 1


def test_outstanding_limiter_reclaims_requests_ib_never_answers():
    clock = FakeClock()
    limiter = OutstandingRequestLimiter(1, max_hold_seconds=60, clock=clock)
    limiter.acquire(1, timeout=0)

    clock.now = 59
    assert not limiter.acquire(2, timeout=0)
    clock.now = 60
    assert limiter.acquire(2, timeout=0)


def test_outstanding_limiter_keeps_background_requests_to_their_share():
    limiter = OutstandingRequestLimiter(3, background_capacity=1)

    assert limiter.acquire(1, timeout=0, is_background=lambda: True)
    assert not limiter.acquire(2, timeout=0, is_background=lambda: True)
    assert limiter.acquire(3, timeout=0)
    assert limiter.acquire(4, timeout=0)


def test_outstanding_limiter_serves_waiting_foreground_requests_first():
    limiter = OutstandingRequestLimiter(1, background_capacity=1)
    limiter.acquire(1, timeout=0)
    foreground = threading.Thread(
        target=limiter.acquire, args=(2,), kwargs={"timeout": 2}
    )
    background = threading.Thread(
        target=limiter.acquire,
        args=(3,),
        kwargs={"timeout": 2, "is_background": lambda: True},
    )
    background.start()
    foreground.start()
    wait_until(lambda: limiter.foreground_waiting == 1)

    limiter.release(1)
    foreground.join()
    assert set(limiter.held_since) == {2}
    limiter.release(2)
    background.join()
    assert set(limiter.held_since) == {3}


def test_outstanding_limiter_gives_urgent_requests_the_next_free_slot():
    limiter = OutstandingRequestLimiter(1)
    limiter.acquire(1, timeout=0)
    bulk = threading.Thread(target=limiter.acquire, args=(2,), kwargs={"timeout": 2})
    urgent = threading.Thread(
        target=limiter.acquire, args=(3,), kwargs={"timeout": 2, "urgent": True}
    )
    bulk.start()
    wait_until(lambda: limiter.foreground_waiting == 1)
    urgent.start()
    wait_until(lambda: limiter.urgent_waiting == 1)

    limiter.release(1)
    urgent.join()
    assert set(limiter.held_since) == {3}
    limiter.release(3)
    bulk.join()
    assert set(limiter.held_since) == {2}

    assert not limiter.acquire(4, timeout=0, urgent=True)
    assert limiter.urgent_waiting == 0


def test_outstanding_limiter_lets_a_promoted_request_use_any_free_slot():
    limiter = OutstandingRequestLimiter(2, background_capacity=1)
    limiter.acquire(1, timeout=0, is_background=lambda: True)
    background = [True]
    acquired = []
    waiter = threading.Thread(
        target=lambda: acquired.append(
            limiter.acquire(2, timeout=2, is_background=lambda: background[0])
        )
    )
    waiter.start()

    background[0] = False
    waiter.join()
    assert acquired == [True]
    assert limiter.foreground_waiting == 0


def test_ib_app_holds_contract_lookup_slots_until_ib_answers():
    app = IbPortfolioApp()
    slots = app.contract_details_slots
    slots.acquire(70_000, timeout=0)
    slots.acquire(70_001, timeout=0)

    app.contractDetailsEnd(70_000)
    assert slots.outstanding() == 1
    app.error(70_001, 200, "No security definition has been found for the request")
    assert slots.outstanding() == 0
