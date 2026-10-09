import threading
from time import perf_counter

from app.ib.app import IbPortfolioApp
from app.ib.option_quotes import wait_for_quote_fields
from tests.ib.fakes import (
    FakeOptionChainIbApp,
    deliver_ticks_later,
)


FULL_QUOTE = {"bid": 1, "ask": 1.2, "delta": 0.4}


def quote_timing_app(req_ids):
    app = FakeOptionChainIbApp()
    ready = threading.Event()
    for req_id in req_ids:
        app.option_market_data[req_id] = {}
        app.option_market_ready_by_req_id[req_id] = ready
    return app, ready


def test_quote_wait_completes_once_every_quote_has_bid_ask_and_delta():
    app, ready = quote_timing_app([1, 2])
    deliver_ticks_later(app, 0.02, {1: FULL_QUOTE, 2: FULL_QUOTE})
    started_at = perf_counter()

    timing = wait_for_quote_fields(
        app,
        [1, 2],
        ready,
        max_wait_seconds=4,
        settle_seconds=2,
        started_at=started_at,
    )

    assert perf_counter() - started_at < 1
    assert timing[1] is not None


def test_quote_wait_settles_when_new_fields_stop_arriving():
    app, ready = quote_timing_app([1, 2])
    deliver_ticks_later(app, 0.02, {1: FULL_QUOTE, 2: {"ask": 1.2, "delta": 0.3}})
    started_at = perf_counter()

    timing = wait_for_quote_fields(
        app,
        [1, 2],
        ready,
        max_wait_seconds=4,
        settle_seconds=0.1,
        started_at=started_at,
    )

    elapsed = perf_counter() - started_at
    assert 0.08 <= elapsed < 1
    assert timing[0] is not None
    assert timing[1] is None


def test_quote_wait_does_not_settle_before_a_quoted_contract_has_its_delta():
    app, ready = quote_timing_app([1, 2])
    deliver_ticks_later(app, 0.02, {1: FULL_QUOTE, 2: {"bid": 1, "ask": 1.2}})
    deliver_ticks_later(app, 0.3, {2: {"delta": 0.3}})
    started_at = perf_counter()

    timing = wait_for_quote_fields(
        app,
        [1, 2],
        ready,
        max_wait_seconds=4,
        settle_seconds=0.1,
        started_at=started_at,
    )

    assert 0.28 <= perf_counter() - started_at < 1
    assert timing[1] is not None


def test_quote_wait_does_not_settle_while_a_contract_has_no_data():
    app, ready = quote_timing_app([1, 2])
    deliver_ticks_later(app, 0.02, {1: FULL_QUOTE})
    started_at = perf_counter()

    wait_for_quote_fields(
        app,
        [1, 2],
        ready,
        max_wait_seconds=0.4,
        settle_seconds=0.05,
        started_at=started_at,
    )

    assert 0.38 <= perf_counter() - started_at < 1


def test_quote_wait_for_contracts_that_never_quote_ends_at_the_maximum():
    app, ready = quote_timing_app([1])
    started_at = perf_counter()

    timing = wait_for_quote_fields(
        app,
        [1],
        ready,
        max_wait_seconds=0.2,
        started_at=started_at,
    )

    assert 0.18 <= perf_counter() - started_at < 0.6
    assert timing == (None, None, None)


def test_quote_wait_ignores_line_limited_contracts():
    app, ready = quote_timing_app([1, 2])
    app.limit_errors_by_req_id = {2: 101}
    deliver_ticks_later(app, 0.02, {1: FULL_QUOTE})
    started_at = perf_counter()

    timing = wait_for_quote_fields(
        app,
        [1, 2],
        ready,
        max_wait_seconds=4,
        settle_seconds=2,
        started_at=started_at,
    )

    assert perf_counter() - started_at < 1
    assert timing[1] is not None


def test_quote_wait_stops_when_cancelled():
    app, ready = quote_timing_app([1])
    cancel_event = threading.Event()
    threading.Timer(0.02, cancel_event.set).start()
    started_at = perf_counter()

    wait_for_quote_fields(
        app,
        [1],
        ready,
        max_wait_seconds=4,
        cancel_event=cancel_event,
        started_at=started_at,
    )

    assert perf_counter() - started_at < 1


def test_ib_option_tick_signals_only_its_subscription_group():
    app = IbPortfolioApp()
    first_ready = threading.Event()
    second_ready = threading.Event()
    app.option_market_req_to_key.update({90_000: (100, "C"), 90_001: (100, "P")})
    app.option_market_ready_by_req_id.update({90_000: first_ready, 90_001: second_ready})

    app.tickPrice(90_001, 1, 1.2, None)

    assert not first_ready.is_set()
    assert second_ready.is_set()