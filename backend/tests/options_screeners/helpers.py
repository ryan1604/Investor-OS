from datetime import datetime
from zoneinfo import ZoneInfo

from app.options.types import (
    FullOptionChainSnapshot,
    ScannerContractSelection,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.options.domain import OptionMetadata
from app.options.store import CompletedDailyBar
from app.schemas import OptionContractIdentity, OptionsScreenerQuoteRefreshRequest


class HistoricalProvider:
    def __init__(self) -> None:
        self.requests = []

    def fetch_daily_bars(self, ticker, start_date, end_date):
        self.requests.append((ticker, start_date, end_date))
        return [
            CompletedDailyBar(
                ticker=ticker,
                trading_date=end_date.isoformat(),
                open=100,
                high=101,
                low=99,
                close=100,
            )
        ]


class MetadataProvider:
    def __init__(self, strikes=None) -> None:
        self.strikes = strikes if strikes is not None else [80, 85, 90, 95, 100, 105]

    def fetch_option_metadata(self, ticker):
        return OptionMetadata(
            expirations=[
                "2026-06-15",
                "2026-06-22",
                "2026-06-26",
                "2026-07-30",
            ],
            strikes=self.strikes,
        )


class ScannerProvider:
    def __init__(self, *, right="P", ask=1.1, delta=-0.2) -> None:
        self.right = right
        self.ask = ask
        self.delta = delta
        self.contract_request = None
        self.quote_request = None

    def fetch_option_contracts(
        self,
        ticker,
        lookups,
        right,
        cancel_event,
    ):
        self.contract_request = (ticker, lookups, right)
        return ScannerContractSelection(
            contracts=[
                contract(expiration, strike, con_id=index, right=right)
                for index, (expiration, strike) in enumerate(lookups, start=1)
            ]
        )

    def fetch_quotes(self, contracts, cancel_event):
        self.quote_request = contracts
        return [
            ScannerOptionQuote(
                contract=current,
                bid=1,
                ask=self.ask,
                delta=self.delta,
            )
            for current in contracts
        ]

    def refresh_quote(self, **kwargs):
        return ScannerOptionQuote(
            contract=contract(
                kwargs["expiration"],
                kwargs["strike"],
                con_id=kwargs["con_id"] or 99,
                right=self.right,
            ),
            bid=1,
            ask=1.2,
            delta=-0.2,
        )

    def cancel(self):
        return


class EmptyProvider:
    def fetch_chain_quotes(self, ticker, expiration, strikes):
        return {}

    def stream_chain_quotes(self, ticker, expiration, strikes, stop_event):
        return iter(())

    def stream_daily_bar_updates(self, ticker, stop_event):
        return iter(())


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
