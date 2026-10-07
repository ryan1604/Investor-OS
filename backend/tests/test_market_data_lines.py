import threading

from app.ib.market_data_lines import MarketDataLineBudget, market_data_line_budget


def test_budget_grants_up_to_capacity_and_releases_lines():
    budget = MarketDataLineBudget(10)

    assert budget.try_acquire("screener", 8) == 8
    assert budget.try_acquire("chain", 5) == 2
    assert budget.try_acquire("screener", 1) == 0

    budget.release("screener", 8)

    assert budget.used() == 2
    assert budget.usage_by_group() == {"chain": 2}


def test_minimum_grant_is_all_or_nothing():
    budget = MarketDataLineBudget(3)

    assert budget.try_acquire("chain", 4, minimum=4) == 0
    assert budget.try_acquire("chain", 4, minimum=2) == 3


def test_unmet_higher_priority_demand_blocks_lower_priority_groups():
    budget = MarketDataLineBudget(10)
    owner = object()
    budget.try_acquire("screener", 10)

    assert budget.try_acquire("chain", 6, owner=owner) == 0
    budget.release("screener", 10)

    assert budget.try_acquire("screener", 10) == 4
    assert budget.try_acquire("chain", 6, owner=owner) == 6
    assert budget.try_acquire("portfolio", 1) == 0


def test_cleared_demand_no_longer_blocks_lower_priority_groups():
    budget = MarketDataLineBudget(4)
    owner = object()
    budget.try_acquire("portfolio", 10, owner=owner)
    budget.release("portfolio", 4)

    assert budget.try_acquire("screener", 1) == 0

    budget.clear_pending(owner)

    assert budget.try_acquire("screener", 1) == 1


def test_blocking_acquire_waits_for_released_lines():
    budget = MarketDataLineBudget(2)
    budget.try_acquire("chain", 2)
    granted = []
    thread = threading.Thread(
        target=lambda: granted.append(budget.acquire("screener", 5, timeout=1)),
    )

    thread.start()
    threading.Event().wait(0.05)
    budget.release("chain", 1)
    thread.join()

    assert granted == [1]


def test_blocking_acquire_returns_zero_on_stop_or_timeout():
    budget = MarketDataLineBudget(1)
    budget.try_acquire("chain", 1)
    stop_event = threading.Event()
    stop_event.set()

    assert budget.acquire("screener", 1, stop_event=stop_event) == 0
    assert budget.acquire("screener", 1, timeout=0.01) == 0
    assert budget.pending_by_owner == {}


def test_waiting_higher_priority_request_blocks_lower_priority_grants():
    budget = MarketDataLineBudget(2)
    budget.try_acquire("screener", 2)
    granted = []
    thread = threading.Thread(
        target=lambda: granted.append(budget.acquire("chain", 2, minimum=2, timeout=1)),
    )

    thread.start()
    threading.Event().wait(0.05)
    budget.release("screener", 1)
    assert budget.try_acquire("screener", 1) == 0
    budget.release("screener", 1)
    thread.join()

    assert granted == [2]


def test_apps_without_budget_get_an_unlimited_one():
    class App:
        pass

    app = App()
    budget = market_data_line_budget(app)

    assert budget.try_acquire("screener", 500) == 500
    assert market_data_line_budget(app) is budget


def test_snapshot_reports_every_group_with_lines_in_use_and_waiting_demand():
    budget = MarketDataLineBudget(5)
    budget.try_acquire("portfolio", 3)
    budget.try_acquire("chain", 4, owner="chain-stream")

    snapshot = budget.snapshot()

    assert snapshot.capacity == 5
    assert snapshot.used == 5
    assert snapshot.used_by_group == {
        "portfolio": 3, "chart": 0, "chain": 2, "quote_refresh": 0, "screener": 0,
    }
    assert snapshot.pending_by_group["chain"] == 2
    assert sum(snapshot.pending_by_group.values()) == 2

    budget.release("portfolio", 3)
    budget.clear_pending("chain-stream")

    assert budget.snapshot().used_by_group["portfolio"] == 0
    assert budget.snapshot().pending_by_group["chain"] == 0
