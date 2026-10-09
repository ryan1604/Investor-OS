from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from threading import Lock
from time import monotonic

from app.ib.contracts import option_right_code
from app.options.types import ScannerOptionContract
from app.schemas import OptionQuote
from app.timing import elapsed_ms

# Preserve the existing logging channel when moving the stream helpers.
logger = logging.getLogger("app.options.client")


class ChainStreamTiming:
    def __init__(
        self,
        ticker: str,
        expiration: str,
        started_at: float,
        context_ms: float,
        stream_strikes: list[float],
        contract_strike_count: int,
    ) -> None:
        self.ticker = ticker
        self.expiration = expiration
        self.started_at = started_at
        self.context_ms = context_ms
        self.stream_strikes = stream_strikes
        self.contract_strike_count = contract_strike_count
        self.first_quote_logged = False
        self.delta_bounds_logged = False

    def observe(
        self,
        quotes: dict[tuple[float, str], OptionQuote],
        delta_bounds: tuple[float | None, float | None],
    ) -> None:
        if not self.first_quote_logged and any(
            quote.bid is not None or quote.ask is not None
            for quote in quotes.values()
        ):
            self.first_quote_logged = True
            logger.info(
                "Option chain first quoted row ticker=%s expiration=%s "
                "context_ms=%.1f elapsed_ms=%.1f",
                self.ticker,
                self.expiration,
                self.context_ms,
                elapsed_ms(self.started_at),
            )
        lower_bound, upper_bound = delta_bounds
        if self.delta_bounds_logged or lower_bound is None or upper_bound is None:
            return
        self.delta_bounds_logged = True
        logger.info(
            "Option chain delta bounds ticker=%s expiration=%s lower=%s upper=%s "
            "window_strikes=%s stream_strikes=%s contract_strikes=%s "
            "lower_at_stream_edge=%s upper_at_stream_edge=%s elapsed_ms=%.1f",
            self.ticker,
            self.expiration,
            lower_bound,
            upper_bound,
            sum(
                1
                for strike in self.stream_strikes
                if lower_bound <= strike <= upper_bound
            ),
            len(self.stream_strikes),
            self.contract_strike_count,
            lower_bound == self.stream_strikes[0],
            upper_bound == self.stream_strikes[-1],
            elapsed_ms(self.started_at),
        )


OPTION_CHAIN_RECENTER_STRIKES = 3


class OptionChainRotation:
    """Live window and rotating refresh plan for one open option chain.

    The stream provider reads the live window and takes rotation batches from
    its own threads; the client reports merged quotes through observe().
    """

    def __init__(
        self,
        ticker: str,
        expiration: str,
        display_strikes: list[float],
        contracts: list[ScannerOptionContract],
        live_strikes: list[float],
        underlying_price: float | None,
        *,
        recenter_strikes: int = OPTION_CHAIN_RECENTER_STRIKES,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.ticker = ticker
        self.expiration = expiration
        self.display_strikes = sorted(display_strikes)
        self.contracts_by_strike: dict[float, list[ScannerOptionContract]] = {}
        for contract in contracts:
            self.contracts_by_strike.setdefault(contract.strike, []).append(contract)
        self.live_strike_count = len(live_strikes)
        self.live_strikes = sorted(live_strikes)
        self.center_price = underlying_price
        self.recenter_strikes = recenter_strikes
        self.clock = clock
        self.delta_bounds: tuple[float | None, float | None] = (None, None)
        self.pending_strikes: list[float] = []
        self.passes = 0
        self.pass_strike_count = 0
        self.pass_started_at: float | None = None
        self.captured_at: dict[tuple[float, str], float] = {}
        self.lock = Lock()

    def live_contracts(self) -> list[ScannerOptionContract]:
        with self.lock:
            live_strikes = list(self.live_strikes)
            center_price = self.center_price
        return nearest_contracts_first(
            [
                contract
                for strike in live_strikes
                for contract in self.contracts_by_strike.get(strike, [])
            ],
            center_price,
        )

    def next_batch(self, max_contracts: int) -> list[ScannerOptionContract]:
        """Return whole outer strikes to quote next, starting a pass as needed."""
        with self.lock:
            if not self.pending_strikes:
                self._start_pass()
            live_strike_set = set(self.live_strikes)
            batch: list[ScannerOptionContract] = []
            while self.pending_strikes:
                strike = self.pending_strikes[0]
                strike_contracts = self.contracts_by_strike.get(strike, [])
                if batch and len(batch) + len(strike_contracts) > max_contracts:
                    break
                self.pending_strikes.pop(0)
                if strike not in live_strike_set:
                    batch.extend(strike_contracts)
            return batch

    def record(self, keys: Iterable[tuple[float, str]]) -> None:
        captured_at = self.clock()
        with self.lock:
            for key in keys:
                self.captured_at[key] = captured_at

    def observe(
        self,
        quotes: dict[tuple[float, str], OptionQuote],
        delta_bounds: tuple[float | None, float | None],
    ) -> None:
        """Track delta bounds and recenter the live window on large moves."""
        at_the_money = at_the_money_strike(self.display_strikes, quotes)
        with self.lock:
            self.delta_bounds = delta_bounds
            if at_the_money is None:
                return
            center = self.live_strikes[len(self.live_strikes) // 2]
            moved = abs(
                self.display_strikes.index(at_the_money)
                - self.display_strikes.index(center)
            )
            if moved < self.recenter_strikes:
                return
            self.center_price = at_the_money
            self.live_strikes = capped_chain_strikes(
                self.display_strikes,
                at_the_money,
                self.live_strike_count,
            )
        logger.info(
            "Option chain live window recentered ticker=%s expiration=%s "
            "center_strike=%s moved_strikes=%s",
            self.ticker,
            self.expiration,
            at_the_money,
            moved,
        )

    def _start_pass(self) -> None:
        now = self.clock()
        if self.pass_strike_count and self.pass_started_at is not None:
            logger.info(
                "Option chain rotation pass complete ticker=%s expiration=%s "
                "pass=%s strikes=%s oldest_quote_age_ms=%.0f elapsed_ms=%.0f",
                self.ticker,
                self.expiration,
                self.passes,
                self.pass_strike_count,
                (now - min(self.captured_at.values(), default=now)) * 1_000,
                (now - self.pass_started_at) * 1_000,
            )
        live_strike_set = set(self.live_strikes)
        strikes = [
            strike for strike in self.display_strikes if strike not in live_strike_set
        ]
        if self.passes:
            # Later passes refresh the displayed range plus one strike beyond
            # each bound, so the range can widen when the market moves.
            lower_bound, upper_bound = self.delta_bounds
            lower_index = (
                self.display_strikes.index(lower_bound) - 1
                if lower_bound is not None
                else 0
            )
            upper_index = (
                self.display_strikes.index(upper_bound) + 1
                if upper_bound is not None
                else len(self.display_strikes) - 1
            )
            strikes = [
                strike
                for strike in strikes
                if lower_index
                <= self.display_strikes.index(strike)
                <= upper_index
            ]
        # Outward from the live window on both sides.
        self.pending_strikes = sorted(
            strikes,
            key=lambda strike: (
                abs(strike - self.center_price)
                if self.center_price is not None
                else 0,
                strike,
            ),
        )
        self.passes += 1
        self.pass_strike_count = len(self.pending_strikes)
        self.pass_started_at = now


def at_the_money_strike(
    strikes: list[float],
    quotes: dict[tuple[float, str], OptionQuote],
) -> float | None:
    quoted = []
    for strike in strikes:
        call = quotes.get((strike, "C"))
        if call is not None and call.delta is not None:
            quoted.append((abs(call.delta - 0.5), strike))
    return min(quoted)[1] if quoted else None


def capped_chain_strikes(
    strikes: list[float],
    underlying_price: float | None,
    maximum_count: int,
) -> list[float]:
    if len(strikes) <= maximum_count or underlying_price is None:
        return strikes[:maximum_count]

    return sorted(
        sorted(strikes, key=lambda strike: (abs(strike - underlying_price), strike))[
            :maximum_count
        ]
    )


OPTION_RIGHT_CODES = ("C", "P")


def option_contract_preference(contract: ScannerOptionContract) -> tuple[int, int]:
    return (0 if contract.exchange == "SMART" else 1, contract.con_id)


def preferred_chain_contracts(
    contracts: Iterable[ScannerOptionContract],
) -> list[ScannerOptionContract]:
    selected: dict[tuple[float, str], ScannerOptionContract] = {}
    for contract in contracts:
        key = (contract.strike, option_right_code(contract.right))
        current = selected.get(key)
        if current is None or option_contract_preference(
            contract
        ) < option_contract_preference(current):
            selected[key] = contract
    return sorted(
        selected.values(),
        key=lambda contract: (contract.strike, contract.right),
    )


def preferred_chain_contracts_from_entries(
    entries: dict[tuple[float, str], tuple[ScannerOptionContract, ...]],
) -> list[ScannerOptionContract]:
    return preferred_chain_contracts(
        contract for contracts in entries.values() for contract in contracts
    )


def nearest_contracts_first(
    contracts: list[ScannerOptionContract],
    underlying_price: float | None,
) -> list[ScannerOptionContract]:
    if underlying_price is None:
        return contracts
    return sorted(
        contracts,
        key=lambda contract: (
            abs(contract.strike - underlying_price),
            contract.strike,
            contract.right,
        ),
    )
