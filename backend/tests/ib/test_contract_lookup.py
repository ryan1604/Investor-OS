import threading
from concurrent.futures import ThreadPoolExecutor

from app.ib.contracts import us_option_contract
from app.ib.contract_lookup import (
    fetch_exact_contract_lookups,
    send_contract_details_request,
)
from app.options.types import ContractLookupPriority
from tests.ib.fakes import SharedSlotExactOptionChainIbApp


def test_exact_lookups_from_concurrent_callers_share_one_outstanding_cap():
    strikes = list(range(90, 120))
    app = SharedSlotExactOptionChainIbApp(contract_strikes=strikes, slots=4)
    lookups = [("2026-07-31", strike) for strike in strikes]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda right: fetch_exact_contract_lookups(
                    app,
                    "SPY",
                    lookups,
                    right,
                    timeout_seconds=2,
                ),
                ["C", "P"],
            )
        )

    assert all(
        len(contracts) == 1 for result in results for contracts in result.values()
    )
    assert app.max_in_flight == 4


def test_background_exact_lookups_stay_within_their_share_of_slots():
    strikes = list(range(90, 100))
    app = SharedSlotExactOptionChainIbApp(contract_strikes=strikes, slots=4)
    app.contract_details_slots.background_capacity = 1

    result = fetch_exact_contract_lookups(
        app,
        "SPY",
        [("2026-07-31", strike) for strike in strikes],
        "C",
        timeout_seconds=2,
        priority=ContractLookupPriority(background=True),
    )

    assert all(len(contracts) == 1 for contracts in result.values())
    assert app.max_in_flight == 1


def test_abandoned_contract_lookup_keeps_its_slot_until_ib_answers():
    app = SharedSlotExactOptionChainIbApp(contract_strikes=[], slots=1)
    app.reqContractDetails = lambda req_id, contract: app.contract_detail_requests.append(
        req_id
    )
    contract = us_option_contract("SPY", expiration="2026-07-31", strike=500, right="C")

    assert send_contract_details_request(app, 1, contract, timeout_seconds=0.05) > 0
    assert send_contract_details_request(app, 2, contract, timeout_seconds=0.05) == 0
    app.contract_details_slots.release(1)
    assert send_contract_details_request(app, 3, contract, timeout_seconds=0.05) > 0

    assert app.contract_detail_requests == [1, 3]


def test_slot_wait_with_its_own_limit_leaves_ib_the_full_timeout():
    app = SharedSlotExactOptionChainIbApp(contract_strikes=[], slots=1)
    app.reqContractDetails = lambda req_id, contract: app.contract_detail_requests.append(
        req_id
    )
    contract = us_option_contract("SPY", expiration="2026-07-31", strike=500, right="C")
    app.contract_details_slots.acquire(1, timeout=0)
    threading.Timer(0.1, app.contract_details_slots.release, args=(1,)).start()

    remaining = send_contract_details_request(
        app, 2, contract, timeout_seconds=0.05, slot_timeout_seconds=2
    )

    assert remaining == 0.05
    assert app.contract_detail_requests == [2]