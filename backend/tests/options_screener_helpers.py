from datetime import datetime
from zoneinfo import ZoneInfo

from app.options.client import (
    FullOptionChainSnapshot,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.schemas import OptionContractIdentity, OptionsScreenerQuoteRefreshRequest


class FullChainClient:
    def __init__(self, quotes):
        self.quotes = quotes
        self.requests = []
        self.cancelled = False
        self.line_limited_contracts = 0

    def get_full_option_chain(self, ticker, **kwargs):
        self.requests.append((ticker, kwargs))
        return FullOptionChainSnapshot(
            ticker=ticker,
            underlying_price=100,
            underlying_price_captured_at=datetime(
                2026,
                6,
                15,
                10,
                tzinfo=ZoneInfo("America/New_York"),
            ),
            contracts=self.quotes,
            line_limited_contracts=self.line_limited_contracts,
        )

    def cancel_scanner(self):
        self.cancelled = True

    def refresh_option_quote(self, **kwargs):
        self.requests.append(("refresh", kwargs))
        return self.quotes[0]


def put_contract(expiration, strike, *, con_id, **kwargs):
    return contract(expiration, strike, con_id=con_id, right="P", **kwargs)


def call_contract(expiration, strike, *, con_id, **kwargs):
    return contract(expiration, strike, con_id=con_id, right="C", **kwargs)


def contract(
    expiration,
    strike,
    *,
    con_id,
    right,
    exchange="SMART",
    multiplier="100",
    trading_class="AAPL",
):
    return ScannerOptionContract(
        con_id=con_id,
        ticker="AAPL",
        expiration=expiration,
        strike=strike,
        right=right,
        exchange=exchange,
        currency="USD",
        multiplier=multiplier,
        trading_class=trading_class,
        local_symbol=f"AAPL {expiration} {strike} {right}",
    )


def put_quote(expiration, strike, con_id, **kwargs):
    kwargs.setdefault("delta", -0.2)
    return quote(expiration, strike, con_id, right="P", **kwargs)


def call_quote(expiration, strike, con_id, **kwargs):
    kwargs.setdefault("delta", 0.2)
    return quote(expiration, strike, con_id, right="C", **kwargs)


def quote(
    expiration,
    strike,
    con_id,
    *,
    right,
    exchange="SMART",
    multiplier="100",
    trading_class="AAPL",
    bid=1,
    ask=1.1,
    delta=0.2,
):
    return ScannerOptionQuote(
        contract=contract(
            expiration,
            strike,
            con_id=con_id,
            right=right,
            exchange=exchange,
            multiplier=multiplier,
            trading_class=trading_class,
        ),
        bid=bid,
        ask=ask,
        delta=delta,
    )


def refresh_request(
    *,
    strike=100,
    right="PUT",
    con_id=123,
):
    side = "P" if right == "PUT" else "C"
    return OptionsScreenerQuoteRefreshRequest(
        ticker="AAPL",
        expiration="2026-07-17",
        strike=strike,
        right=right,
        contract=OptionContractIdentity(
            con_id=con_id,
            local_symbol=f"AAPL 2026-07-17 {strike} {side}",
        ),
    )
