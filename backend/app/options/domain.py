from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.options.indicators import DailyClose
from app.options.store import CompletedDailyBar, StoredDailyBar
from app.schemas import OptionChainRow, OptionDailyBar, OptionQuote

MIN_OPTION_CHAIN_DELTA = 0.095

MAX_HISTORICAL_CHUNK_DAYS = 365


@dataclass(frozen=True)
class OptionMetadata:
    expirations: list[str]
    strikes: list[float]


def missing_completed_ranges(
    cached_bars: list[StoredDailyBar],
    *,
    start_date: date,
    latest_completed_date: date,
    current_date: date,
) -> list[tuple[date, date]]:
    if latest_completed_date < start_date:
        return [(current_date, current_date)]

    if not cached_bars:
        return [(start_date, current_date)]

    last_cached_date = date.fromisoformat(cached_bars[-1].trading_date)

    return [(last_cached_date, current_date)]


def chunk_date_range(
    start_date: date,
    end_date: date,
    *,
    max_days: int = MAX_HISTORICAL_CHUNK_DAYS,
) -> list[tuple[date, date]]:
    if start_date > end_date:
        return []

    chunks: list[tuple[date, date]] = []
    chunk_start = start_date

    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=max_days - 1), end_date)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)

    return chunks


def same_month_day_years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year - years)


def to_option_daily_bar(bar: CompletedDailyBar) -> OptionDailyBar:
    return OptionDailyBar(
        date=bar.trading_date,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def to_daily_closes(bars: list[CompletedDailyBar]) -> list[DailyClose]:
    return [
        DailyClose(
            trading_date=bar.trading_date,
            close=bar.close,
        )
        for bar in bars
    ]


def days_to_expiration(
    expiration: str,
    current_date: date | None = None,
) -> int | None:
    try:
        expiration_date = date.fromisoformat(expiration)
    except ValueError:
        return None

    return (expiration_date - (current_date or date.today())).days


def sorted_expirations(expirations: list[str]) -> list[str]:
    return sorted(expirations, key=expiration_sort_key)


def expiration_sort_key(expiration: str) -> date:
    try:
        return date.fromisoformat(expiration)
    except ValueError:
        return date.max


def option_chain_strikes(strikes: list[float]) -> list[float]:
    return sorted({strike for strike in strikes if strike > 0})


def option_chain_rows(
    strikes: list[float],
    quotes: dict[tuple[float, str], OptionQuote],
) -> list[OptionChainRow]:
    sorted_strikes = sorted(strikes)
    lower_bound, upper_bound = option_chain_delta_bounds(sorted_strikes, quotes)
    if lower_bound is None or upper_bound is None or lower_bound > upper_bound:
        return [
            OptionChainRow(
                strike=strike,
                call=quotes.get((strike, "C")),
                put=quotes.get((strike, "P")),
            )
            for strike in sorted_strikes
            if quotes.get((strike, "C")) is not None
            or quotes.get((strike, "P")) is not None
        ]

    return [
        OptionChainRow(
            strike=strike,
            call=quotes.get((strike, "C")),
            put=quotes.get((strike, "P")),
        )
        for strike in sorted_strikes
        if lower_bound <= strike <= upper_bound
    ]


def option_quote_above_minimum(quote: OptionQuote | None) -> bool:
    if quote is None:
        return False
    return quote.delta is not None and abs(quote.delta) > MIN_OPTION_CHAIN_DELTA


def option_chain_delta_bounds(
    sorted_strikes: list[float],
    quotes: dict[tuple[float, str], OptionQuote],
) -> tuple[float | None, float | None]:
    lower_bound = next(
        (
            strike
            for strike in sorted_strikes
            if option_quote_above_minimum(quotes.get((strike, "P")))
        ),
        None,
    )
    upper_bound = next(
        (
            strike
            for strike in reversed(sorted_strikes)
            if option_quote_above_minimum(quotes.get((strike, "C")))
        ),
        None,
    )
    return lower_bound, upper_bound


def to_option_quote(
    values: dict[str, float | int | None],
    *,
    strike: float,
    right: str,
) -> OptionQuote:
    bid = numeric_or_none(values.get("bid"))
    ask = numeric_or_none(values.get("ask"))

    return OptionQuote(
        local_symbol=string_or_none(values.get("local_symbol")),
        delta=numeric_or_none(values.get("delta")),
        bid=bid,
        bid_size=int_or_none(values.get("bid_size")),
        ask=ask,
        ask_size=int_or_none(values.get("ask_size")),
        mid=mid_price(bid, ask),
        last=numeric_or_none(values.get("last")),
        close=numeric_or_none(values.get("close")),
        model_price=numeric_or_none(values.get("model_price")),
        change_percent=change_percent(
            numeric_or_none(values.get("last")),
            numeric_or_none(values.get("close")),
        ),
        volume=int_or_none(values.get("volume")),
        open_interest=int_or_none(values.get("open_interest")),
        gamma=numeric_or_none(values.get("gamma")),
        theta=numeric_or_none(values.get("theta")),
        implied_volatility_percent=numeric_or_none(
            values.get("implied_volatility_percent")
        ),
        breakeven=breakeven(strike, ask, right),
    )


def mid_price(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def breakeven(strike: float, ask: float | None, right: str) -> float | None:
    if ask is None:
        return None
    if right == "C":
        return strike + ask
    if right == "P":
        return strike - ask
    return None


def change_percent(last: float | None, close: float | None) -> float | None:
    if last is None or close is None or close == 0:
        return None
    return ((last - close) / close) * 100


def numeric_or_none(value: object) -> float | None:
    return value if isinstance(value, int | float) else None


def int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
