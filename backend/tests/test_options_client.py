import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.ib.app import IbPortfolioApp
from app.ib.contracts import us_equity_contract, us_option_contract
from app.ib.options import (
    IbHistoricalDailyBarStreamProvider,
    IbOptionChainSnapshotProvider,
    IbOptionChainStreamProvider,
    IbHistoricalDailyBarProvider,
    IbOptionMetadataProvider,
)
from app.options.client import (
    AnalysisUnderlyingPriceCache,
    CachedOptionMetadataProvider,
    OptionsClient,
    OptionsDataUnavailable,
    ScannerOptionContract,
    capped_chain_strikes,
)
from app.options.domain import (
    OptionMetadata,
    bounded_strikes,
    chunk_date_range,
    option_chain_rows,
    to_option_quote,
)
from app.options.store import CompletedDailyBar, OptionsDailyBarStore
from app.schemas import OptionQuote


class FakeHistoricalProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[str, date, date]] = []

    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        self.requests.append((ticker, start_date, end_date))
        bars = []
        current_date = start_date

        while current_date <= end_date:
            bars.append(
                CompletedDailyBar(
                    ticker=ticker,
                    trading_date=current_date.isoformat(),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1_000,
                )
            )
            current_date += timedelta(days=1)

        return bars


class EmptyHistoricalProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[str, date, date]] = []

    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        self.requests.append((ticker, start_date, end_date))
        return []


class OverlapHistoricalProvider:
    def __init__(self, barrier: threading.Barrier) -> None:
        self.barrier = barrier
        self.requests: list[tuple[str, date, date]] = []

    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        self.requests.append((ticker, start_date, end_date))
        if len(self.requests) == 1:
            self.barrier.wait(timeout=1)
        return [
            CompletedDailyBar(
                ticker=ticker,
                trading_date=end_date.isoformat(),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1_000,
            )
        ]


class FakeMetadataProvider:
    def __init__(
        self,
        expirations: list[str] | None = None,
        strikes: list[float] | None = None,
    ) -> None:
        self.expirations = expirations or []
        self.strikes = strikes or []
        self.requests: list[str] = []

    def fetch_expirations(self, ticker: str) -> list[str]:
        self.requests.append(ticker)
        return self.expirations

    def fetch_option_metadata(self, ticker: str):
        self.requests.append(ticker)
        return OptionMetadata(expirations=self.expirations, strikes=self.strikes)


class OverlapMetadataProvider(FakeMetadataProvider):
    def __init__(
        self,
        barrier: threading.Barrier,
        *,
        error: Exception | None = None,
    ) -> None:
        super().__init__(strikes=[100])
        self.barrier = barrier
        self.error = error

    def fetch_option_metadata(self, ticker: str):
        self.requests.append(ticker)
        self.barrier.wait(timeout=1)
        if self.error is not None:
            raise self.error
        return OptionMetadata(expirations=self.expirations, strikes=self.strikes)


class FakeChainProvider:
    def __init__(
        self,
        quotes: dict[tuple[float, str], OptionQuote] | None = None,
        contract_strikes: list[float] | None = None,
    ) -> None:
        self.quotes = quotes or {}
        self.contract_strikes = contract_strikes
        self.requests: list[tuple[str, str, list[float]]] = []
        self.quote_requests: list[list[ScannerOptionContract]] = []
        self.request_event = threading.Event()

    def fetch_chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> list[ScannerOptionContract]:
        self.request_event.set()
        self.requests.append((ticker, expiration, strikes))
        actual_strikes = (
            self.contract_strikes if self.contract_strikes is not None else strikes
        )
        return [
            ScannerOptionContract(
                con_id=index + 1,
                ticker=ticker,
                expiration=expiration,
                strike=strike,
                right=right,
                exchange="SMART",
                currency="USD",
                multiplier="100",
                trading_class=ticker,
                local_symbol=f"{ticker}{index}{right}",
            )
            for index, (strike, right) in enumerate(
                (strike, right)
                for strike in actual_strikes
                if strike in strikes
                for right in ("C", "P")
            )
        ]

    def fetch_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
    ) -> dict[tuple[float, str], OptionQuote]:
        self.quote_requests.append(list(contracts))
        strikes = {contract.strike for contract in contracts}
        return {
            key: quote
            for key, quote in self.quotes.items()
            if key[0] in strikes
            and any(
                contract.strike == key[0] and contract.right == key[1]
                for contract in contracts
            )
        }


class SlowChainProvider(FakeChainProvider):
    def __init__(
        self,
        quotes: dict[tuple[float, str], OptionQuote] | None = None,
        contract_strikes: list[float] | None = None,
    ) -> None:
        super().__init__(quotes, contract_strikes)
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch_chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> list[ScannerOptionContract]:
        self.started.set()
        self.release.wait(timeout=1)
        return super().fetch_chain_contracts(ticker, expiration, strikes)


class BlockingFirstChainProvider(FakeChainProvider):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.first_started = threading.Event()
        self.lock = threading.Lock()
        self.blocked_first_request = False

    def fetch_chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> list[ScannerOptionContract]:
        with self.lock:
            should_block = not self.blocked_first_request
            self.blocked_first_request = True

        if should_block:
            self.first_started.set()
            self.release.wait(timeout=1)

        return super().fetch_chain_contracts(ticker, expiration, strikes)


def wait_until(predicate, *, timeout_seconds: float = 1) -> None:
    deadline = datetime.now().timestamp() + timeout_seconds
    while datetime.now().timestamp() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    assert predicate()


def test_option_metadata_cache_reuses_expirations_and_strikes():
    provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[95, 100, 105],
    )
    cache = CachedOptionMetadataProvider(provider)

    expirations = cache.fetch_expirations(" aapl ")
    metadata = cache.fetch_option_metadata("AAPL")

    assert expirations == ["2026-06-19"]
    assert metadata.strikes == [95, 100, 105]
    assert provider.requests == ["AAPL"]


def test_option_metadata_cache_refreshes_expired_entries():
    provider = FakeMetadataProvider(strikes=[100])
    current_time = [0.0]
    cache = CachedOptionMetadataProvider(
        provider,
        ttl_seconds=900,
        current_time=lambda: current_time[0],
    )

    assert cache.fetch_option_metadata("MSFT").strikes == [100]
    provider.strikes = [105]
    current_time[0] = 900

    assert cache.fetch_option_metadata("MSFT").strikes == [105]
    assert provider.requests == ["MSFT", "MSFT"]


def test_option_metadata_cache_isolates_tickers():
    provider = FakeMetadataProvider(strikes=[100])
    cache = CachedOptionMetadataProvider(provider)

    cache.fetch_option_metadata("AAPL")
    provider.strikes = [200]

    assert cache.fetch_option_metadata("MSFT").strikes == [200]
    assert cache.fetch_option_metadata("AAPL").strikes == [100]
    assert provider.requests == ["AAPL", "MSFT"]


def test_analysis_underlying_price_cache_expires_and_isolates_tickers():
    current_time = [0.0]
    cache = AnalysisUnderlyingPriceCache(
        ttl_seconds=60,
        current_time=lambda: current_time[0],
    )

    cache.set(" aapl ", 100)

    assert cache.get("AAPL") == 100
    assert cache.get("MSFT") is None

    current_time[0] = 60

    assert cache.get("AAPL") is None


class FakeChainStreamProvider:
    def __init__(
        self,
        quotes: list[tuple[tuple[float, str], OptionQuote]] | None = None,
    ) -> None:
        self.quotes = quotes or []
        self.requests: list[tuple[str, str, list[float]]] = []

    def stream_chain_quotes(self, contracts, stop_event):
        first_contract = contracts[0] if contracts else None
        ticker = first_contract.ticker if first_contract else ""
        expiration = first_contract.expiration if first_contract else ""
        strikes = sorted({contract.strike for contract in contracts})
        self.requests.append((ticker, expiration, strikes))

        for key, quote in self.quotes:
            if stop_event.is_set():
                break
            if key[0] in strikes:
                yield key, quote


class FakeHistoricalStreamProvider:
    def __init__(self, bars: list[CompletedDailyBar] | None = None) -> None:
        self.bars = bars or []
        self.requests: list[str] = []

    def stream_daily_bar_updates(self, ticker, stop_event):
        self.requests.append(ticker)

        for bar in self.bars:
            if stop_event.is_set():
                break
            yield bar


def make_client(
    tmp_path,
    provider,
    metadata_provider=None,
    chain_provider=None,
    chain_stream_provider=None,
    historical_stream_provider=None,
    current_date_provider=date.today,
    chain_context_workers=2,
):
    store = OptionsDailyBarStore(tmp_path / "options.sqlite3")
    explicit_metadata_provider = metadata_provider or FakeMetadataProvider()
    explicit_chain_provider = chain_provider or FakeChainProvider()
    explicit_chain_stream_provider = chain_stream_provider or FakeChainStreamProvider()
    explicit_historical_stream_provider = (
        historical_stream_provider or FakeHistoricalStreamProvider()
    )
    return (
        OptionsClient(
            store,
            provider,
            explicit_metadata_provider,
            explicit_chain_provider,
            explicit_chain_stream_provider,
            explicit_historical_stream_provider,
            current_date_provider=current_date_provider,
            chain_context_workers=chain_context_workers,
        ),
        store,
    )


def test_first_ticker_load_hydrates_ten_year_daily_bar_window(tmp_path):
    provider = FakeHistoricalProvider()
    client, _store = make_client(tmp_path, provider)

    result = client.load_daily_bars(
        "aapl",
        current_date=date(2026, 5, 30),
    )

    assert result.ticker == "AAPL"
    assert provider.requests[0] == (
        "AAPL",
        date(2016, 5, 30),
        date(2017, 5, 29),
    )
    assert provider.requests[-1][2] == date(2026, 5, 30)
    assert all(
        (end_date - start_date).days < 365
        for _ticker, start_date, end_date in provider.requests
    )
    assert result.metrics is not None
    assert result.metrics.cache_state == "cold"
    assert result.metrics.history_chunk_count == len(provider.requests)
    assert result.metrics.ib_wait_ms >= 0
    assert result.metrics.cache_hit_ratio == 0
    assert result.metrics.payload_bytes > 0


def test_repeat_ticker_load_refreshes_latest_cached_completed_bar(tmp_path):
    provider = FakeHistoricalProvider()
    client, _store = make_client(tmp_path, provider)

    client.load_daily_bars("MSFT", current_date=date(2026, 5, 30))
    provider.requests.clear()
    client.load_daily_bars("MSFT", current_date=date(2026, 5, 30))

    assert provider.requests == [
        ("MSFT", date(2026, 5, 29), date(2026, 5, 30)),
    ]


def test_underlying_price_uses_focused_recent_bar_request(tmp_path):
    provider = FakeHistoricalProvider()
    client, _store = make_client(tmp_path, provider)

    price = client.get_underlying_price(
        " aapl ",
        current_date=date(2026, 5, 30),
    )

    assert price == 100
    assert provider.requests == [
        ("AAPL", date(2026, 5, 23), date(2026, 5, 30)),
    ]


def test_underlying_price_reports_unavailable_recent_bars(tmp_path):
    provider = EmptyHistoricalProvider()
    client, _store = make_client(tmp_path, provider)

    with pytest.raises(
        OptionsDataUnavailable,
        match="Current price is unavailable for AAPL.",
    ):
        client.get_underlying_price("AAPL", current_date=date(2026, 5, 30))


def test_repeat_recently_listed_ticker_load_does_not_request_pre_cache_history(
    tmp_path,
):
    provider = EmptyHistoricalProvider()
    client, store = make_client(tmp_path, provider)
    store.upsert_completed_bars(
        [
            CompletedDailyBar(
                "SOFI",
                "2020-11-30",
                10,
                11,
                9,
                10,
                1_000,
            ),
        ],
        current_date=date(2026, 5, 30),
    )

    client.load_daily_bars("SOFI", current_date=date(2026, 5, 30))

    assert provider.requests[0] == (
        "SOFI",
        date(2020, 11, 30),
        date(2021, 11, 29),
    )
    assert provider.requests[-1][2] == date(2026, 5, 30)
    assert all(
        start_date >= date(2020, 11, 30)
        for _ticker, start_date, _end_date in provider.requests
    )


def test_newly_completed_daily_bars_are_upserted_on_later_loads(tmp_path):
    provider = FakeHistoricalProvider()
    client, store = make_client(tmp_path, provider)

    client.load_daily_bars("TSLA", current_date=date(2026, 5, 30), years=1)
    provider.requests.clear()
    client.load_daily_bars("TSLA", current_date=date(2026, 5, 31), years=1)

    bars = store.get_completed_bars(
        "TSLA",
        start_date="2026-05-30",
        end_date="2026-05-30",
    )

    assert provider.requests == [
        ("TSLA", date(2026, 5, 29), date(2026, 5, 31)),
    ]
    assert [bar.trading_date for bar in bars] == ["2026-05-30"]


def test_current_day_bar_is_returned_without_being_finalized(tmp_path):
    provider = FakeHistoricalProvider()
    client, store = make_client(tmp_path, provider)

    result = client.load_daily_bars(
        "NVDA",
        current_date=date(2026, 5, 30),
        years=1,
    )

    stored_current_bars = store.get_completed_bars(
        "NVDA",
        start_date="2026-05-30",
        end_date="2026-05-30",
    )

    assert result.current_bar is not None
    assert result.current_bar.trading_date == "2026-05-30"
    assert stored_current_bars == []


def test_stream_chart_replaces_current_candle_and_recalculates_indicators(tmp_path):
    provider = FakeHistoricalProvider()
    historical_stream_provider = FakeHistoricalStreamProvider(
        [
            CompletedDailyBar(
                "AAPL",
                "2026-05-30",
                100,
                121,
                99,
                120,
                2_000,
            ),
        ]
    )
    client, store = make_client(
        tmp_path,
        provider,
        historical_stream_provider=historical_stream_provider,
    )
    client.load_daily_bars("AAPL", current_date=date(2026, 5, 30), years=1)

    messages = list(
        client.stream_chart(
            "aapl",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )
    stored_current_bars = store.get_completed_bars(
        "AAPL",
        start_date="2026-05-30",
        end_date="2026-05-30",
    )

    assert historical_stream_provider.requests == ["AAPL"]
    assert len(messages) == 1
    assert messages[0].ticker == "AAPL"
    assert messages[0].candle.close == 120
    assert messages[0].bollinger_band.date == "2026-05-30"
    assert messages[0].bollinger_band.middle == 101
    assert messages[0].rsi.date == "2026-05-30"
    assert messages[0].rsi.value == 100
    assert stored_current_bars == []


def test_stream_chart_reuses_completed_window_for_same_day_ticks(tmp_path):
    provider = FakeHistoricalProvider()
    historical_stream_provider = FakeHistoricalStreamProvider(
        [
            CompletedDailyBar("AAPL", "2026-05-30", 100, 121, 99, 120, 2_000),
            CompletedDailyBar("AAPL", "2026-05-30", 100, 122, 99, 121, 2_100),
        ]
    )
    client, store = make_client(
        tmp_path,
        provider,
        historical_stream_provider=historical_stream_provider,
    )
    client.load_daily_bars("AAPL", current_date=date(2026, 5, 30), years=1)
    original_get_completed_bars = store.get_completed_bars
    read_count = 0

    def counted_get_completed_bars(*args, **kwargs):
        nonlocal read_count
        read_count += 1
        return original_get_completed_bars(*args, **kwargs)

    store.get_completed_bars = counted_get_completed_bars

    messages = list(
        client.stream_chart(
            "aapl",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert [message.candle.close for message in messages] == [120, 121]
    assert read_count == 1


def test_stream_chart_ignores_prior_day_initial_snapshot(tmp_path):
    provider = FakeHistoricalProvider()
    historical_stream_provider = FakeHistoricalStreamProvider(
        [
            CompletedDailyBar(
                "AAPL",
                "2026-05-29",
                99,
                101,
                98,
                100,
                1_000,
            ),
            CompletedDailyBar(
                "AAPL",
                "2026-05-30",
                100,
                121,
                99,
                120,
                2_000,
            ),
        ]
    )
    client, _store = make_client(
        tmp_path,
        provider,
        historical_stream_provider=historical_stream_provider,
    )
    client.load_daily_bars("AAPL", current_date=date(2026, 5, 30), years=1)

    messages = list(
        client.stream_chart(
            "aapl",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert [message.candle.date for message in messages] == ["2026-05-30"]


def test_stream_chart_finalizes_prior_active_candle_after_date_rollover(tmp_path):
    provider = FakeHistoricalProvider()
    historical_stream_provider = FakeHistoricalStreamProvider(
        [
            CompletedDailyBar("AAPL", "2026-05-30", 100, 101, 99, 100, 1_000),
            CompletedDailyBar("AAPL", "2026-05-31", 100, 103, 99, 102, 2_000),
        ]
    )
    current_dates = iter([date(2026, 5, 30), date(2026, 5, 31)])
    client, store = make_client(
        tmp_path,
        provider,
        historical_stream_provider=historical_stream_provider,
        current_date_provider=lambda: next(current_dates),
    )
    store.upsert_completed_bars(
        [
            CompletedDailyBar(
                "AAPL",
                f"2026-05-{day:02d}",
                100,
                101,
                99,
                100,
                1_000,
            )
            for day in range(10, 30)
        ],
        current_date=date(2026, 5, 30),
    )

    messages = list(
        client.stream_chart(
            "AAPL",
            stop_event=threading.Event(),
        )
    )

    assert [message.candle.date for message in messages] == [
        "2026-05-30",
        "2026-05-31",
    ]
    assert [message.bollinger_band.date for message in messages] == [
        "2026-05-30",
        "2026-05-31",
    ]
    assert [message.rsi.date for message in messages] == [
        "2026-05-30",
        "2026-05-31",
    ]
    assert [
        bar.trading_date
        for bar in store.get_completed_bars(
            "AAPL",
            start_date="2026-05-30",
            end_date="2026-05-31",
        )
    ] == ["2026-05-30"]


def test_get_analysis_returns_chart_indicators_without_loading_expirations(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(["2026-07-17", "2026-06-19"])
    client, _store = make_client(tmp_path, provider, metadata_provider)

    response = client.get_analysis(
        "aapl",
        current_date=date(2026, 5, 30),
    )

    assert response.ticker == "AAPL"
    assert response.underlying_price == 100
    assert response.candles[0].date == "2016-05-30"
    assert response.candles[-1].date == "2026-05-30"
    assert len(response.bollinger_bands) == len(response.candles)
    assert response.bollinger_bands[18].middle is None
    assert response.bollinger_bands[19].middle == 100
    assert len(response.rsi) == len(response.candles)
    assert response.rsi[13].value is None
    assert response.rsi[14].value == 100
    assert metadata_provider.requests == []


def test_get_expirations_returns_sorted_expirations(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(["2026-07-17", "2026-06-19"])
    client, _store = make_client(tmp_path, provider, metadata_provider)

    response = client.get_expirations(
        "aapl",
        current_date=date(2026, 5, 30),
    )

    assert response.ticker == "AAPL"
    assert [expiration.date for expiration in response.expirations] == [
        "2026-06-19",
        "2026-07-17",
    ]
    assert [expiration.days_to_expiration for expiration in response.expirations] == [
        20,
        48,
    ]
    assert response.selected_expiration == "2026-06-19"
    assert metadata_provider.requests == ["AAPL"]


def test_get_expirations_prefetches_selected_and_nearby_contracts(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=[
            "2026-06-19",
            "2026-06-26",
            "2026-07-03",
            "2026-07-10",
        ],
        strikes=[70, 80, 90, 100, 110, 120, 130],
    )
    chain_provider = FakeChainProvider()
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    client.get_analysis("AAPL", current_date=date(2026, 5, 30))
    response = client.get_expirations("AAPL", current_date=date(2026, 5, 30))

    wait_until(lambda: len(chain_provider.requests) == 3)
    client.shutdown()

    assert response.selected_expiration == "2026-06-19"
    assert chain_provider.requests == [
        ("AAPL", "2026-06-19", [70, 80, 90, 100, 110, 120, 130]),
        ("AAPL", "2026-06-26", [70, 80, 90, 100, 110, 120, 130]),
        ("AAPL", "2026-07-03", [70, 80, 90, 100, 110, 120, 130]),
    ]
    assert chain_provider.quote_requests == []


def test_get_expirations_skips_prefetch_without_analysis_price(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[100],
    )
    chain_provider = FakeChainProvider()
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    response = client.get_expirations("AAPL", current_date=date(2026, 5, 30))

    assert response.selected_expiration == "2026-06-19"
    assert chain_provider.requests == []


def test_visible_chain_request_does_not_wait_for_unrelated_prefetch(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19", "2026-07-17"],
        strikes=[100],
    )
    chain_provider = BlockingFirstChainProvider()
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    client.get_analysis("AAPL", current_date=date(2026, 5, 30))
    client.get_expirations("AAPL", current_date=date(2026, 5, 30))
    assert chain_provider.first_started.wait(timeout=1)

    response = client.get_chain(
        "AAPL",
        "2026-07-17",
        current_date=date(2026, 5, 30),
    )
    chain_provider.release.set()
    wait_until(lambda: len(chain_provider.requests) == 2)
    client.shutdown()

    assert response.expiration == "2026-07-17"
    assert chain_provider.requests[0] == ("AAPL", "2026-07-17", [100])


def test_get_analysis_rejects_empty_ticker(tmp_path):
    provider = FakeHistoricalProvider()
    client, _store = make_client(tmp_path, provider)

    try:
        client.get_analysis("   ", current_date=date(2026, 5, 30))
    except OptionsDataUnavailable as error:
        assert str(error) == "Ticker is required."
    else:
        raise AssertionError("Expected empty ticker to be rejected.")


def test_get_analysis_rejects_payloads_without_daily_price_data(tmp_path):
    provider = EmptyHistoricalProvider()
    metadata_provider = FakeMetadataProvider(["2026-06-19"])
    client, _store = make_client(tmp_path, provider, metadata_provider)

    try:
        client.get_analysis("hims", current_date=date(2026, 5, 30))
    except OptionsDataUnavailable as error:
        assert str(error) == "No daily price data is available for HIMS."
    else:
        raise AssertionError("Expected missing daily price data to be rejected.")


def test_get_chain_returns_bounded_call_and_put_rows(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        strikes=[50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150],
    )
    chain_provider = FakeChainProvider(
        {
            (90, "C"): OptionQuote(
                delta=0.2, bid=1, ask=1.4, mid=1.2, breakeven=91.4
            ),
            (90, "P"): OptionQuote(
                delta=-0.2, bid=0.8, ask=1.2, mid=1, breakeven=88.8
            ),
            (100, "C"): OptionQuote(
                delta=0.5, bid=2, ask=2.4, mid=2.2, breakeven=102.4
            ),
            (100, "P"): OptionQuote(
                delta=-0.5, bid=1.8, ask=2.2, mid=2, breakeven=97.8
            ),
        }
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    response = client.get_chain(
        "aapl",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert response.ticker == "AAPL"
    assert response.expiration == "2026-06-19"
    assert response.underlying_price == 100
    assert [row.strike for row in response.rows] == [90, 100]
    assert response.rows[0].call is not None
    assert response.rows[0].call.mid == 1.2
    assert response.rows[0].put is not None
    assert response.rows[0].put.breakeven == 88.8
    assert chain_provider.requests == [
        ("AAPL", "2026-06-19", [70, 80, 90, 100, 110, 120, 130]),
    ]


def test_get_chain_overlaps_daily_bar_and_metadata_fallback_requests(tmp_path):
    barrier = threading.Barrier(2)
    provider = OverlapHistoricalProvider(barrier)
    metadata_provider = OverlapMetadataProvider(barrier)
    client, _store = make_client(tmp_path, provider, metadata_provider)

    response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert response.underlying_price == 100
    assert metadata_provider.requests == ["AAPL"]


def test_get_chain_uses_bounded_shared_chain_context_executor(tmp_path):
    barrier = threading.Barrier(2)
    provider = OverlapHistoricalProvider(barrier)
    metadata_provider = OverlapMetadataProvider(barrier)
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_context_workers=2,
    )
    executor = client.chain_context_executor

    response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert response.underlying_price == 100
    assert client.chain_context_executor is executor


def test_concurrent_chain_requests_share_contract_hydration(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[95, 100],
    )
    chain_provider = SlowChainProvider(
        {
            (95, "P"): OptionQuote(delta=-0.2, bid=1),
            (100, "C"): OptionQuote(delta=0.2, bid=1),
        }
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )
    client.analysis_underlying_price_cache.set("AAPL", 100)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.get_chain,
            "AAPL",
            "2026-06-19",
            current_date=date(2026, 5, 30),
        )
        assert chain_provider.started.wait(timeout=1)
        second = executor.submit(
            client.get_chain,
            "AAPL",
            "2026-06-19",
            current_date=date(2026, 5, 30),
        )
        chain_provider.release.set()
        first_response = first.result(timeout=1)
        second_response = second.result(timeout=1)

    assert [row.strike for row in first_response.rows] == [95, 100]
    assert [row.strike for row in second_response.rows] == [95, 100]
    assert chain_provider.requests == [
        ("AAPL", "2026-06-19", [95, 100]),
    ]
    assert len(chain_provider.quote_requests) == 2


def test_get_chain_does_not_cache_failed_metadata_refresh(tmp_path):
    barrier = threading.Barrier(2)
    provider = OverlapHistoricalProvider(barrier)
    metadata_provider = OverlapMetadataProvider(
        barrier,
        error=OptionsDataUnavailable("Metadata refresh failed."),
    )
    client, _store = make_client(tmp_path, provider, metadata_provider)

    try:
        client.get_chain(
            "AAPL",
            "2026-06-19",
            current_date=date(2026, 5, 30),
        )
    except OptionsDataUnavailable as error:
        assert str(error) == "Metadata refresh failed."
    else:
        raise AssertionError("Expected metadata refresh failure.")

    assert client.metadata_provider.entries == {}


def test_get_chain_reuses_metadata_but_fetches_live_quotes(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[100])
    chain_provider = FakeChainProvider(
        {
            (100, "C"): OptionQuote(delta=0.5, bid=1),
            (100, "P"): OptionQuote(delta=-0.5, bid=1),
        },
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    first_response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    chain_provider.quotes = {
        (100, "C"): OptionQuote(delta=0.5, bid=2),
        (100, "P"): OptionQuote(delta=-0.5, bid=1),
    }
    second_response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert first_response.rows[0].call is not None
    assert first_response.rows[0].call.bid == 1
    assert second_response.rows[0].call is not None
    assert second_response.rows[0].call.bid == 2
    assert metadata_provider.requests == ["AAPL"]
    assert chain_provider.requests == [
        ("AAPL", "2026-06-19", [100]),
    ]
    assert len(chain_provider.quote_requests) == 2


def test_get_chain_omits_metadata_strikes_without_selected_expiration_contracts(
    tmp_path,
):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100])
    chain_provider = FakeChainProvider(
        {
            (90, "P"): OptionQuote(delta=-0.2, bid=1),
            (100, "C"): OptionQuote(delta=0.2, bid=1),
            (95, "C"): OptionQuote(delta=0.2, bid=1),
            (95, "P"): OptionQuote(delta=-0.2, bid=1),
        },
        contract_strikes=[90, 100],
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    response = client.get_chain(
        "HIMS",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert [row.strike for row in response.rows] == [90, 100]
    assert chain_provider.requests == [
        ("HIMS", "2026-06-19", [90, 95, 100]),
    ]


def test_get_chain_cached_contracts_still_exclude_unresolved_strikes(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100])
    chain_provider = FakeChainProvider(
        {
            (90, "P"): OptionQuote(delta=-0.2, bid=1),
            (100, "C"): OptionQuote(delta=0.2, bid=1),
            (95, "C"): OptionQuote(delta=0.2, bid=1),
            (95, "P"): OptionQuote(delta=-0.2, bid=1),
        },
        contract_strikes=[90, 100],
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    first_response = client.get_chain(
        "HIMS",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    chain_provider.contract_strikes = [90, 95, 100]
    second_response = client.get_chain(
        "HIMS",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert [row.strike for row in first_response.rows] == [90, 100]
    assert [row.strike for row in second_response.rows] == [90, 100]
    assert chain_provider.requests == [
        ("HIMS", "2026-06-19", [90, 95, 100]),
    ]


def test_analysis_chain_and_stream_setup_share_one_daily_bar_refresh(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[100],
    )
    client, _store = make_client(tmp_path, provider, metadata_provider)

    client.get_analysis("AAPL", current_date=date(2026, 5, 30))
    provider.requests.clear()

    chain_response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    stream = client.stream_chain(
        "AAPL",
        "2026-06-19",
        stop_event=threading.Event(),
        current_date=date(2026, 5, 30),
    )
    stream_snapshot = next(stream)

    assert chain_response.underlying_price == 100
    assert stream_snapshot.type == "snapshot"
    assert provider.requests == []


def test_rest_chain_and_stream_reuse_contracts_without_duplicate_streams(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[100],
    )
    chain_provider = FakeChainProvider(
        {
            (100, "C"): OptionQuote(delta=0.2, bid=1),
            (100, "P"): OptionQuote(delta=-0.2, bid=1),
        },
    )
    chain_stream_provider = FakeChainStreamProvider(
        [((100, "C"), OptionQuote(delta=0.25, bid=2))],
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
        chain_stream_provider,
    )
    client.analysis_underlying_price_cache.set("AAPL", 100)

    rest_response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    stream = client.stream_chain(
        "AAPL",
        "2026-06-19",
        stop_event=threading.Event(),
        current_date=date(2026, 5, 30),
    )
    stream_snapshot = next(stream)
    stream_update = next(stream)

    assert rest_response.rows[0].call is not None
    assert rest_response.rows[0].call.bid == 1
    assert stream_snapshot.rows is not None
    assert stream_snapshot.rows[0].call is not None
    assert stream_snapshot.rows[0].call.bid == 1
    assert stream_update.row is not None
    assert stream_update.row.call is not None
    assert stream_update.row.call.bid == 2
    assert chain_provider.requests == [
        ("AAPL", "2026-06-19", [100]),
    ]
    assert len(chain_provider.quote_requests) == 1
    assert chain_stream_provider.requests == [
        ("AAPL", "2026-06-19", [100]),
    ]


def test_chain_refreshes_daily_bars_after_analysis_price_cache_expires(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[100],
    )
    client, _store = make_client(tmp_path, provider, metadata_provider)
    current_time = [0.0]
    client.analysis_underlying_price_cache = AnalysisUnderlyingPriceCache(
        ttl_seconds=60,
        current_time=lambda: current_time[0],
    )

    client.get_analysis("AAPL", current_date=date(2026, 5, 30))
    provider.requests.clear()
    current_time[0] = 60

    response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert response.underlying_price == 100
    assert provider.requests == [
        ("AAPL", date(2026, 5, 29), date(2026, 5, 30)),
    ]


def test_bounded_strikes_keeps_atm_count_when_percent_range_is_sparse():
    strikes = [10, 20, 30, 40, 50, 90, 100, 110, 150, 160, 170]

    assert bounded_strikes(strikes, 100, range_percent=0.05, minimum_count=5) == [
        50,
        90,
        100,
        110,
        150,
    ]


def test_option_chain_rows_uses_put_floor_and_call_ceiling():
    rows = option_chain_rows(
        [90, 95, 100, 105, 110],
        {
            (90, "P"): OptionQuote(delta=-0.095, bid=1),
            (95, "P"): OptionQuote(delta=-0.1, bid=1),
            (100, "C"): OptionQuote(delta=0.08, bid=1),
            (105, "C"): OptionQuote(delta=0.1, bid=1),
            (110, "C"): OptionQuote(delta=0.095, bid=1),
        },
    )

    assert [row.strike for row in rows] == [95, 100, 105]
    assert rows[0].put is not None
    assert rows[1].call is not None
    assert rows[2].call is not None


def test_option_chain_rows_keeps_quoted_rows_when_delta_is_missing():
    rows = option_chain_rows(
        [90, 95, 100],
        {
            (90, "C"): OptionQuote(delta=None, bid=1, ask=1.2),
            (100, "P"): OptionQuote(delta=None, bid=0.8, ask=1),
        },
    )

    assert [row.strike for row in rows] == [90, 100]
    assert rows[0].call is not None
    assert rows[0].put is None
    assert rows[1].call is None
    assert rows[1].put is not None


def test_option_chain_rows_keeps_delta_window_when_bounds_exist():
    rows = option_chain_rows(
        [90, 95, 100, 105, 110],
        {
            (90, "C"): OptionQuote(delta=None, bid=1),
            (95, "P"): OptionQuote(delta=-0.1, bid=1),
            (100, "P"): OptionQuote(delta=None, bid=1),
            (105, "C"): OptionQuote(delta=0.1, bid=1),
            (110, "P"): OptionQuote(delta=None, bid=1),
        },
    )

    assert [row.strike for row in rows] == [95, 100, 105]


def test_option_chain_rows_keeps_quotes_for_inverted_partial_delta_bounds():
    rows = option_chain_rows(
        [90, 95, 100, 105],
        {
            (90, "C"): OptionQuote(delta=0.1, bid=1),
            (105, "P"): OptionQuote(delta=-0.1, bid=1),
        },
    )

    assert [row.strike for row in rows] == [90, 105]
    assert rows[0].call is not None
    assert rows[1].put is not None


def test_get_chain_preserves_missing_quote_values(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[100])
    chain_provider = FakeChainProvider(
        {
            (100, "C"): OptionQuote(delta=0.5, bid=1),
            (100, "P"): OptionQuote(delta=-0.5, bid=1),
        }
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    response = client.get_chain(
        "MSFT",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert response.rows[0].call is not None
    assert response.rows[0].call.bid == 1
    assert response.rows[0].call.ask is None
    assert response.rows[0].call.mid is None
    assert response.rows[0].call.breakeven is None
    assert response.rows[0].put is not None


def test_get_chain_keeps_contract_quotes_when_delta_is_missing(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[95, 100])
    chain_provider = FakeChainProvider(
        {
            (95, "C"): OptionQuote(delta=None, bid=1, ask=1.2),
            (100, "P"): OptionQuote(delta=None, bid=0.8, ask=1),
        }
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    response = client.get_chain(
        "MSFT",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert [row.strike for row in response.rows] == [95, 100]
    assert response.rows[0].call is not None
    assert response.rows[0].call.delta is None
    assert response.rows[1].put is not None
    assert response.rows[1].put.delta is None


def test_get_chain_rejects_missing_underlying_price_before_quoting_options(tmp_path):
    provider = EmptyHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 100, 110])
    chain_provider = FakeChainProvider()
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )

    try:
        client.get_chain("SOFI", "2026-06-19", current_date=date(2026, 5, 30))
    except OptionsDataUnavailable as error:
        assert str(error) == "Underlying price is unavailable for SOFI."
    else:
        raise AssertionError("Expected missing underlying price to be rejected.")

    assert chain_provider.requests == []


def test_stream_chain_yields_snapshot_then_row_updates(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 100, 110])
    chain_stream_provider = FakeChainStreamProvider(
        [
            ((100, "C"), OptionQuote(delta=None, bid=1, ask=1.2, mid=1.1)),
            ((100, "P"), OptionQuote(delta=None, bid=0.8, ask=1, mid=0.9)),
        ]
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_stream_provider=chain_stream_provider,
    )
    stop_event = threading.Event()

    messages = list(
        client.stream_chain(
            "msft",
            "2026-06-19",
            stop_event=stop_event,
            current_date=date(2026, 5, 30),
        )
    )

    assert messages[0].type == "snapshot"
    assert messages[0].ticker == "MSFT"
    assert messages[0].rows == []
    assert messages[1].type == "update"
    assert messages[1].row is not None
    assert messages[1].row.strike == 100
    assert messages[1].row.call is not None
    assert messages[1].row.call.bid == 1
    assert messages[1].row.put is None
    assert messages[2].type == "update"
    assert messages[2].row is not None
    assert messages[2].row.call is not None
    assert messages[2].row.put is not None
    assert chain_stream_provider.requests == [
        ("MSFT", "2026-06-19", [90, 100, 110]),
    ]


def test_stream_chain_snapshot_uses_recent_quote_cache(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[100])
    chain_provider = FakeChainProvider(
        {
            (100, "C"): OptionQuote(delta=0.5, bid=1),
            (100, "P"): OptionQuote(delta=-0.5, bid=0.8),
        }
    )
    chain_stream_provider = FakeChainStreamProvider()
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
        chain_stream_provider=chain_stream_provider,
    )

    client.get_chain(
        "MSFT",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    messages = list(
        client.stream_chain(
            "MSFT",
            "2026-06-19",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert messages[0].type == "snapshot"
    assert [row.strike for row in messages[0].rows or []] == [100]
    assert messages[0].rows is not None
    assert messages[0].rows[0].call is not None
    assert messages[0].rows[0].call.bid == 1
    assert messages[0].rows[0].put is not None
    assert messages[0].rows[0].put.bid == 0.8


def test_stream_chain_live_update_replaces_cached_quote(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[100])
    chain_provider = FakeChainProvider(
        {
            (100, "C"): OptionQuote(delta=0.5, bid=1),
            (100, "P"): OptionQuote(delta=-0.5, bid=0.8),
        }
    )
    chain_stream_provider = FakeChainStreamProvider(
        [
            ((100, "C"), OptionQuote(delta=0.5, bid=2)),
        ]
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
        chain_stream_provider=chain_stream_provider,
    )

    client.get_chain(
        "MSFT",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    messages = list(
        client.stream_chain(
            "MSFT",
            "2026-06-19",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )
    second_stream = client.stream_chain(
        "MSFT",
        "2026-06-19",
        stop_event=threading.Event(),
        current_date=date(2026, 5, 30),
    )

    assert messages[0].rows is not None
    assert messages[0].rows[0].call is not None
    assert messages[0].rows[0].call.bid == 1
    assert messages[1].row is not None
    assert messages[1].row.call is not None
    assert messages[1].row.call.bid == 2
    second_snapshot = next(second_stream)
    assert second_snapshot.rows is not None
    assert second_snapshot.rows[0].call is not None
    assert second_snapshot.rows[0].call.bid == 2


def test_stream_chain_quote_cache_expires_quickly(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[100])
    chain_provider = FakeChainProvider(
        {
            (100, "C"): OptionQuote(delta=0.5, bid=1),
            (100, "P"): OptionQuote(delta=-0.5, bid=0.8),
        }
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
        chain_stream_provider=FakeChainStreamProvider(),
    )
    client.quote_cache_ttl_seconds = 0

    response = client.get_chain(
        "MSFT",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    messages = list(
        client.stream_chain(
            "MSFT",
            "2026-06-19",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert [row.strike for row in response.rows] == [100]
    assert messages[0].rows == []


def test_stream_chain_keeps_updates_before_delta_window_exists(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[95, 100, 105])
    chain_stream_provider = FakeChainStreamProvider(
        [
            ((105, "C"), OptionQuote(delta=0.095, bid=1)),
            ((100, "C"), OptionQuote(delta=0.1, bid=1)),
            ((95, "P"), OptionQuote(delta=-0.1, bid=1)),
            ((100, "P"), OptionQuote(delta=-0.1, bid=1)),
        ]
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_stream_provider=chain_stream_provider,
    )

    messages = list(
        client.stream_chain(
            "msft",
            "2026-06-19",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert len(messages) == 5
    assert messages[1].row is not None
    assert messages[1].row.strike == 105
    assert messages[1].row.call is not None
    assert messages[2].row is not None
    assert messages[2].row.strike == 100
    assert messages[2].row.call is not None
    assert messages[2].row.put is None
    assert messages[3].type == "snapshot"
    assert [row.strike for row in messages[3].rows or []] == [95, 100]
    assert messages[4].row is not None
    assert messages[4].row.strike == 100
    assert messages[4].row.call is not None
    assert messages[4].row.put is not None


def test_stream_chain_caps_streamed_strikes(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100, 105, 110])
    chain_stream_provider = FakeChainStreamProvider(
        [
            ((90, "C"), OptionQuote(delta=0.2, bid=1)),
            ((90, "P"), OptionQuote(delta=-0.2, bid=1)),
            ((95, "C"), OptionQuote(delta=0.2, bid=2)),
            ((95, "P"), OptionQuote(delta=-0.2, bid=1)),
            ((100, "C"), OptionQuote(delta=0.2, bid=3)),
        ]
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_stream_provider=chain_stream_provider,
    )
    client.max_chain_stream_strikes = 2

    messages = list(
        client.stream_chain(
            "msft",
            "2026-06-19",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert messages[0].message == "Streaming 2 strike(s) for MSFT 2026-06-19."
    assert messages[0].rows == []
    assert chain_stream_provider.requests == [
        ("MSFT", "2026-06-19", [95, 100]),
    ]


def test_stream_chain_caps_strikes_around_underlying_price():
    assert capped_chain_strikes([687, 688, 689, 710, 711, 712], 711, 3) == [
        710,
        711,
        712,
    ]


def test_option_quote_derives_mid_breakeven_and_change_percent():
    call = to_option_quote(
        {
            "bid": 1,
            "bid_size": 11,
            "ask": 1.4,
            "ask_size": 12,
            "last": 1.5,
            "close": 1.25,
            "model_price": 1.35,
            "delta": 0.45,
            "gamma": 0.02,
            "theta": -0.03,
            "implied_volatility_percent": 42,
            "volume": 10,
            "open_interest": 200,
        },
        strike=100,
        right="C",
    )
    put = to_option_quote({"bid": 2, "ask": 2.6}, strike=100, right="P")

    assert call.mid == 1.2
    assert call.bid_size == 11
    assert call.ask_size == 12
    assert call.close == 1.25
    assert call.model_price == 1.35
    assert call.breakeven == 101.4
    assert call.change_percent == 20
    assert call.delta == 0.45
    assert call.gamma == 0.02
    assert call.theta == -0.03
    assert call.implied_volatility_percent == 42
    assert call.volume == 10
    assert call.open_interest == 200
    assert put.mid == 2.3
    assert put.breakeven == 97.4


def test_chunk_date_range_splits_large_requests():
    chunks = chunk_date_range(
        date(2026, 1, 1),
        date(2026, 1, 10),
        max_days=4,
    )

    assert chunks == [
        (date(2026, 1, 1), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 8)),
        (date(2026, 1, 9), date(2026, 1, 10)),
    ]


def test_us_equity_contract_uses_stock_smart_usd_contract_shape():
    contract = us_equity_contract("sofi")

    assert contract.symbol == "SOFI"
    assert contract.secType == "STK"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"


class FakeHistoricalIbApp:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_historical_req_id = 60_000
        self.historical_bars: dict[int, list[CompletedDailyBar]] = {}
        self.historical_req_tickers: dict[int, str] = {}
        self.historical_data_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.requests = []

    def isConnected(self) -> bool:
        return True

    def reqHistoricalData(
        self,
        req_id,
        contract,
        end_date_time,
        duration,
        bar_size,
        what_to_show,
        use_rth,
        format_date,
        keep_up_to_date,
        chart_options,
    ) -> None:
        self.requests.append(
            (
                req_id,
                contract,
                end_date_time,
                duration,
                bar_size,
                what_to_show,
                use_rth,
                format_date,
                keep_up_to_date,
                chart_options,
            )
        )
        self.historical_bars[req_id] = [
            CompletedDailyBar(
                ticker=contract.symbol,
                trading_date="2026-05-29",
                open=100,
                high=101,
                low=99,
                close=100,
            )
        ]
        self.historical_data_ready_by_req_id[req_id].set()


class InvalidTickerHistoricalIbApp(FakeHistoricalIbApp):
    def reqHistoricalData(self, req_id, contract, *args) -> None:
        self.requests.append((req_id, contract, *args))
        self.request_errors_by_req_id[req_id] = (
            200,
            "No security definition has been found for the request",
        )
        self.historical_data_ready_by_req_id[req_id].set()


def test_ib_historical_provider_requests_daily_trade_bars_for_us_equity():
    app = FakeHistoricalIbApp()
    provider = IbHistoricalDailyBarProvider(app)

    bars = provider.fetch_daily_bars(
        "amd",
        date(2026, 5, 1),
        date(2026, 5, 30),
    )

    request = app.requests[0]
    requested_contract = request[1]
    assert requested_contract.symbol == "AMD"
    assert requested_contract.secType == "STK"
    assert requested_contract.exchange == "SMART"
    assert requested_contract.currency == "USD"
    assert request[2] == "20260530 23:59:59 US/Eastern"
    assert request[3] == "30 D"
    assert request[4] == "1 day"
    assert request[5] == "TRADES"
    assert bars[0].trading_date == "2026-05-29"


def test_ib_historical_provider_rejects_invalid_ticker_without_waiting_for_chunks():
    app = InvalidTickerHistoricalIbApp()
    provider = IbHistoricalDailyBarProvider(app)

    try:
        provider.fetch_daily_bars(
            "invalid",
            date(2016, 5, 30),
            date(2017, 5, 29),
        )
    except OptionsDataUnavailable as error:
        assert str(error) == "Invalid ticker: INVALID."
    else:
        raise AssertionError("Expected invalid ticker to be rejected.")

    assert len(app.requests) == 1
    assert app.historical_bars == {}
    assert app.historical_req_tickers == {}
    assert app.historical_data_ready_by_req_id == {}
    assert app.request_errors_by_req_id == {}


class FakeHistoricalStreamIbApp:
    def __init__(self, *, primary_exchange: str = "NASDAQ") -> None:
        self.primary_exchange = primary_exchange
        self.lock = threading.Lock()
        self.next_historical_req_id = 60_000
        self.next_chart_market_req_id = 110_000
        self.next_contract_details_req_id = 70_000
        self.historical_bars: dict[int, list[CompletedDailyBar]] = {}
        self.historical_req_tickers: dict[int, str] = {}
        self.historical_data_ready_by_req_id: dict[int, threading.Event] = {}
        self.chart_market_req_tickers: dict[int, str] = {}
        self.chart_market_updates_by_req_id: dict[int, list[CompletedDailyBar]] = {}
        self.chart_market_ready_by_req_id: dict[int, threading.Event] = {}
        self.contract_details = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.historical_requests = []
        self.contract_detail_requests = []
        self.market_requests = []
        self.market_data_types = []
        self.cancelled_historical_data = []
        self.cancelled_market_data = []

    def isConnected(self) -> bool:
        return True

    def reqHistoricalData(self, req_id, contract, *args) -> None:
        self.historical_requests.append((req_id, contract, *args))
        self.historical_bars[req_id] = [
            CompletedDailyBar(
                ticker=contract.symbol,
                trading_date="2026-05-30",
                open=100,
                high=102,
                low=99,
                close=101,
            )
        ]
        self.historical_data_ready_by_req_id[req_id].set()

    def reqContractDetails(self, req_id, contract) -> None:
        contract.primaryExchange = self.primary_exchange
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": contract})(),
        ]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_types.append(market_data_type)

    def reqMktData(self, req_id, contract, *args) -> None:
        self.market_requests.append((req_id, contract, *args))
        self.chart_market_updates_by_req_id[req_id] = [
            CompletedDailyBar(
                ticker=contract.symbol,
                trading_date="2026-05-30",
                open=101,
                high=103,
                low=100,
                close=102,
            )
        ]
        self.chart_market_ready_by_req_id[req_id].set()

    def cancelHistoricalData(self, req_id: int) -> None:
        self.cancelled_historical_data.append(req_id)

    def cancelMktData(self, req_id: int) -> None:
        self.cancelled_market_data.append(req_id)


def test_ib_historical_stream_provider_aggregates_direct_market_ticks_and_cleans_up():
    app = FakeHistoricalStreamIbApp()
    provider = IbHistoricalDailyBarStreamProvider(app, wait_seconds=0.01)
    stream = provider.stream_daily_bar_updates("aapl", threading.Event())

    initial_bar = next(stream)
    updated_bar = next(stream)
    stream.close()

    historical_request = app.historical_requests[0]
    market_request = app.market_requests[0]
    assert historical_request[1].symbol == "AAPL"
    assert historical_request[3:] == (
        "2 D",
        "1 day",
        "TRADES",
        1,
        1,
        False,
        [],
    )
    assert market_request[1].symbol == "AAPL"
    assert market_request[1].exchange == "NASDAQ"
    assert market_request[2:] == ("", False, False, [])
    assert app.market_data_types == [3]
    assert initial_bar.close == 101
    assert updated_bar == CompletedDailyBar(
        ticker="AAPL",
        trading_date="2026-05-30",
        open=100,
        high=103,
        low=99,
        close=102,
        volume=None,
    )
    assert app.cancelled_historical_data == []
    assert app.cancelled_market_data == [110_000]
    assert app.historical_bars == {}
    assert app.historical_req_tickers == {}
    assert app.historical_data_ready_by_req_id == {}
    assert app.chart_market_req_tickers == {}
    assert app.chart_market_updates_by_req_id == {}
    assert app.chart_market_ready_by_req_id == {}


def test_ib_historical_stream_provider_requires_primary_exchange():
    app = FakeHistoricalStreamIbApp(primary_exchange="")
    provider = IbHistoricalDailyBarStreamProvider(app)
    stream = provider.stream_daily_bar_updates("aapl", threading.Event())

    try:
        next(stream)
    except OptionsDataUnavailable as error:
        assert str(error) == "Primary market-data exchange is unavailable for AAPL."
    else:
        raise AssertionError("Expected missing primary exchange to be rejected.")

    assert app.market_requests == []


class FakeBar:
    date = "20260529"
    open = 100
    high = 101
    low = 99
    close = 100.5
    volume = 1234


def test_ib_app_historical_data_callback_records_completed_daily_bar():
    app = IbPortfolioApp()
    app.historical_req_tickers[60_000] = "AAPL"
    ready = threading.Event()
    app.historical_data_ready_by_req_id[60_000] = ready

    app.historicalData(60_000, FakeBar())
    app.historicalDataEnd(60_000, "", "")

    assert app.historical_bars[60_000] == [
        CompletedDailyBar(
            ticker="AAPL",
            trading_date="2026-05-29",
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1234,
        )
    ]
    assert ready.is_set()


def test_ib_app_initial_historical_callback_feeds_live_subscription():
    app = IbPortfolioApp()
    ready = threading.Event()
    app.historical_update_req_tickers[60_000] = "AAPL"
    app.historical_updates_by_req_id[60_000] = []
    app.historical_update_ready_by_req_id[60_000] = ready

    app.historicalData(60_000, FakeBar())

    assert app.historical_updates_by_req_id[60_000] == [
        CompletedDailyBar(
            ticker="AAPL",
            trading_date="2026-05-29",
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1234,
        )
    ]
    assert ready.is_set()


def test_ib_app_initial_historical_callback_ignores_invalid_live_bar():
    class InvalidDateBar(FakeBar):
        date = "invalid"

    app = IbPortfolioApp()
    ready = threading.Event()
    app.historical_update_req_tickers[60_000] = "AAPL"
    app.historical_updates_by_req_id[60_000] = []
    app.historical_update_ready_by_req_id[60_000] = ready

    app.historicalData(60_000, InvalidDateBar())

    assert app.historical_updates_by_req_id[60_000] == []
    assert not ready.is_set()


def test_ib_app_historical_update_callback_isolates_live_ticker():
    app = IbPortfolioApp()
    ready = threading.Event()
    other_ready = threading.Event()
    app.historical_update_req_tickers = {
        60_000: "AAPL",
        60_001: "MSFT",
    }
    app.historical_updates_by_req_id = {60_000: [], 60_001: []}
    app.historical_update_ready_by_req_id = {
        60_000: ready,
        60_001: other_ready,
    }

    app.historicalDataUpdate(60_000, FakeBar())

    assert app.historical_updates_by_req_id[60_000][0].ticker == "AAPL"
    assert app.historical_updates_by_req_id[60_001] == []
    assert ready.is_set()
    assert not other_ready.is_set()


def test_ib_app_chart_market_tick_callback_isolates_live_ticker():
    app = IbPortfolioApp()
    ready = threading.Event()
    other_ready = threading.Event()
    app.chart_market_req_tickers = {
        110_000: "AAPL",
        110_001: "MSFT",
    }
    app.chart_market_updates_by_req_id = {110_000: [], 110_001: []}
    app.chart_market_ready_by_req_id = {
        110_000: ready,
        110_001: other_ready,
    }

    app.tickPrice(110_000, 68, 101, None)

    assert app.chart_market_updates_by_req_id[110_000] == [
        CompletedDailyBar(
            ticker="AAPL",
            trading_date=datetime.now(
                ZoneInfo("America/New_York"),
            ).date().isoformat(),
            open=101,
            high=101,
            low=101,
            close=101,
        )
    ]
    assert app.chart_market_updates_by_req_id[110_001] == []
    assert ready.is_set()
    assert not other_ready.is_set()


class FakeContractDetails:
    def __init__(self, con_id: int) -> None:
        contract = us_equity_contract("AAPL")
        contract.conId = con_id
        self.contract = contract


class FakeOptionMetadataIbApp:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_contract_details_req_id = 70_000
        self.next_option_params_req_id = 80_000
        self.contract_details = {}
        self.option_metadata: dict[int, OptionMetadata] = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.option_metadata_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.contract_detail_requests = []
        self.option_parameter_requests = []
        self.market_data_requests = []

    def isConnected(self) -> bool:
        return True

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [FakeContractDetails(12345)]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqSecDefOptParams(
        self,
        req_id,
        underlying_symbol,
        fut_fop_exchange,
        underlying_sec_type,
        underlying_con_id,
    ) -> None:
        self.option_parameter_requests.append(
            (
                req_id,
                underlying_symbol,
                fut_fop_exchange,
                underlying_sec_type,
                underlying_con_id,
            )
        )
        self.option_metadata[req_id] = OptionMetadata(
            expirations=["2026-07-17", "2026-06-19"],
            strikes=[95, 100, 105],
        )
        self.option_metadata_ready_by_req_id[req_id].set()

    def reqMktData(self, *args) -> None:
        self.market_data_requests.append(args)


def test_ib_option_metadata_provider_fetches_expirations_without_market_quotes():
    app = FakeOptionMetadataIbApp()
    provider = IbOptionMetadataProvider(app)

    expirations = provider.fetch_expirations("aapl")

    requested_contract = app.contract_detail_requests[0][1]
    assert requested_contract.symbol == "AAPL"
    assert requested_contract.secType == "STK"
    assert requested_contract.exchange == "SMART"
    assert requested_contract.currency == "USD"
    assert app.option_parameter_requests == [
        (80_000, "AAPL", "", "STK", 12345),
    ]
    assert expirations == ["2026-07-17", "2026-06-19"]
    assert app.market_data_requests == []


class DisconnectedOptionMetadataIbApp(FakeOptionMetadataIbApp):
    def isConnected(self) -> bool:
        return False


class RecoveringOptionMetadataIbApp(FakeOptionMetadataIbApp):
    def __init__(self) -> None:
        super().__init__()
        self.should_respond = False

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        if self.should_respond:
            self.contract_details[req_id] = [FakeContractDetails(12345)]
            self.contract_details_ready_by_req_id[req_id].set()


def test_ib_option_metadata_provider_rejects_disconnected_ib_without_caching():
    cache = CachedOptionMetadataProvider(
        IbOptionMetadataProvider(DisconnectedOptionMetadataIbApp())
    )

    try:
        cache.fetch_option_metadata("AAPL")
    except OptionsDataUnavailable as error:
        assert str(error) == (
            "Options metadata is unavailable while IB is disconnected."
        )
    else:
        raise AssertionError("Expected disconnected metadata request to fail.")

    assert cache.entries == {}


def test_ib_option_metadata_timeout_is_not_cached_and_retry_recovers():
    app = RecoveringOptionMetadataIbApp()
    cache = CachedOptionMetadataProvider(
        IbOptionMetadataProvider(app, timeout_seconds=0.01)
    )

    try:
        cache.fetch_option_metadata("AAPL")
    except OptionsDataUnavailable as error:
        assert str(error) == "Options metadata request timed out for AAPL."
    else:
        raise AssertionError("Expected metadata timeout.")

    app.should_respond = True
    metadata = cache.fetch_option_metadata("AAPL")

    assert metadata.strikes == [95, 100, 105]
    assert len(app.contract_detail_requests) == 2
    assert cache.entries["AAPL"].metadata == metadata


class FakeOptionChainIbApp:
    def __init__(self, contract_strikes: list[float] | None = None) -> None:
        self.lock = threading.Lock()
        self.next_contract_details_req_id = 70_000
        self.next_option_market_req_id = 90_000
        self.contract_strikes = contract_strikes or [95, 100]
        self.contract_details = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.option_market_req_to_key = {}
        self.option_market_data = {}
        self.option_market_data_ready = threading.Event()
        self.contract_detail_requests = []
        self.market_data_requests = []
        self.cancelled_market_data = []
        self.ib_calls_inside_lock: list[str] = []

    def isConnected(self) -> bool:
        return True

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": option_contract})()
            for index, strike in enumerate(self.contract_strikes)
            for option_contract in [
                fake_option_contract(
                    contract,
                    strike,
                    con_id=req_id + index + int(strike * 100),
                )
            ]
        ]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqMktData(
        self,
        req_id,
        contract,
        generic_tick_list,
        snapshot,
        regulatory_snapshot,
        mkt_data_options,
    ) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("reqMktData")
        self.market_data_requests.append(
            (
                req_id,
                contract,
                generic_tick_list,
                snapshot,
                regulatory_snapshot,
                mkt_data_options,
            )
        )
        self.option_market_data[req_id] = {
            "bid": 1,
            "ask": 1.4,
            "last": 1.5,
            "close": 1.25,
            "delta": 0.5,
            "gamma": 0.01,
            "theta": -0.02,
            "implied_volatility_percent": 30,
        }
        self.option_market_data_ready.set()

    def cancelMktData(self, req_id) -> None:
        if self.lock.locked():
            self.ib_calls_inside_lock.append("cancelMktData")
        self.cancelled_market_data.append(req_id)


def fake_option_contract(
    requested_contract,
    strike: float,
    *,
    con_id: int,
    trading_class: str | None = None,
):
    contract = us_option_contract(
        requested_contract.symbol,
        expiration=(
            f"{requested_contract.lastTradeDateOrContractMonth[:4]}-"
            f"{requested_contract.lastTradeDateOrContractMonth[4:6]}-"
            f"{requested_contract.lastTradeDateOrContractMonth[6:8]}"
        ),
        strike=strike,
        right=requested_contract.right,
    )
    contract.conId = con_id
    contract.tradingClass = trading_class or requested_contract.symbol
    contract.localSymbol = f"{requested_contract.symbol}{con_id}{requested_contract.right}"
    return contract


class SlowOptionChainIbApp(FakeOptionChainIbApp):
    def reqMktData(
        self,
        req_id,
        contract,
        generic_tick_list,
        snapshot,
        regulatory_snapshot,
        mkt_data_options,
    ) -> None:
        self.market_data_requests.append(
            (
                req_id,
                contract,
                generic_tick_list,
                snapshot,
                regulatory_snapshot,
                mkt_data_options,
            )
        )
        self.option_market_data[req_id] = {"open_interest": 100}
        self.option_market_data_ready.set()

        def add_prices() -> None:
            with self.lock:
                self.option_market_data[req_id].update({"bid": 1, "ask": 1.4})
                self.option_market_data_ready.set()

        threading.Timer(0.02, add_prices).start()


class SlowContractDetailsOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))

        def add_details() -> None:
            self.contract_details[req_id] = [
                type(
                    "ContractDetails",
                    (),
                    {
                        "contract": fake_option_contract(
                            contract,
                            100,
                            con_id=req_id + 10_000,
                        )
                    },
                )()
            ]
            self.contract_details_ready_by_req_id[req_id].set()

        threading.Timer(0.02, add_details).start()


class TimeoutBroadOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        if contract.strike == 0:
            return

        if contract.strike not in self.contract_strikes:
            self.contract_details_ready_by_req_id[req_id].set()
            return

        self.contract_details[req_id] = [
            type(
                "ContractDetails",
                (),
                {
                    "contract": fake_option_contract(
                        contract,
                        contract.strike,
                        con_id=req_id + int(contract.strike * 100),
                    )
                },
            )()
        ]
        self.contract_details_ready_by_req_id[req_id].set()


class InvalidExactOptionChainIbApp(TimeoutBroadOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        if contract.strike == 0:
            return

        if contract.strike not in self.contract_strikes:
            self.request_errors_by_req_id[req_id] = (200, "No security definition")
            self.contract_details_ready_by_req_id[req_id].set()
            return

        self.contract_details[req_id] = [
            type(
                "ContractDetails",
                (),
                {
                    "contract": fake_option_contract(
                        contract,
                        contract.strike,
                        con_id=req_id + int(contract.strike * 100),
                    )
                },
            )()
        ]
        self.contract_details_ready_by_req_id[req_id].set()


class InvalidBroadOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.request_errors_by_req_id[req_id] = (200, "No security definition")
        self.contract_details_ready_by_req_id[req_id].set()


class EtfOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": option_contract})()
            for index, strike in enumerate(self.contract_strikes)
            for option_contract in [
                fake_option_contract(
                    contract,
                    strike,
                    con_id=req_id + index + int(strike * 100),
                    trading_class=f"{contract.symbol}1",
                )
            ]
        ]
        self.contract_details_ready_by_req_id[req_id].set()


def test_ib_chain_provider_quotes_only_requested_expiration_and_strikes():
    app = FakeOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(app)

    contracts = provider.fetch_chain_contracts(
        "aapl",
        "2026-06-19",
        [95, 100],
    )
    quotes = provider.fetch_chain_quotes(contracts)

    requested_contracts = [request[1] for request in app.market_data_requests]
    assert len(app.contract_detail_requests) == 2
    assert len(requested_contracts) == 4
    assert {contract.conId for contract in requested_contracts}
    assert {contract.lastTradeDateOrContractMonth for contract in requested_contracts} == {
        "20260619",
    }
    assert {contract.strike for contract in requested_contracts} == {95, 100}
    assert {contract.right for contract in requested_contracts} == {"C", "P"}
    assert all(contract.symbol == "AAPL" for contract in requested_contracts)
    assert all(contract.secType == "OPT" for contract in requested_contracts)
    assert all(request[3] is False for request in app.market_data_requests)
    assert app.cancelled_market_data == [90_000, 90_001, 90_002, 90_003]
    assert app.ib_calls_inside_lock == []
    assert quotes[(95, "C")].mid == 1.2
    assert quotes[(95, "C")].breakeven == 96.4


def test_ib_chain_provider_keeps_etf_contracts_with_class_aliases():
    app = EtfOptionChainIbApp(contract_strikes=[710, 711, 712])
    provider = IbOptionChainSnapshotProvider(app)

    contracts = provider.fetch_chain_contracts(
        "qqq",
        "2026-06-29",
        [710, 711, 712],
    )

    assert {contract.strike for contract in contracts} == {710, 711, 712}
    assert {contract.right for contract in contracts} == {"C", "P"}
    assert {contract.trading_class for contract in contracts} == {"QQQ1"}


def test_ib_chain_provider_uses_separate_contract_timeout():
    app = SlowContractDetailsOptionChainIbApp(contract_strikes=[100])
    provider = IbOptionChainSnapshotProvider(
        app,
        timeout_seconds=0.01,
        contract_timeout_seconds=0.05,
    )

    contracts = provider.fetch_chain_contracts(
        "aapl",
        "2026-06-19",
        [100],
    )
    quotes = provider.fetch_chain_quotes(contracts)

    assert {contract.right for contract in contracts} == {"C", "P"}
    assert set(quotes) == {(100, "C"), (100, "P")}


def test_ib_chain_provider_falls_back_to_exact_contracts_after_broad_timeout():
    app = TimeoutBroadOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.01,
    )

    contracts = provider.fetch_chain_contracts(
        "hims",
        "2026-07-31",
        [95, 100, 105],
    )
    quotes = provider.fetch_chain_quotes(contracts)

    assert {contract.strike for contract in contracts} == {95, 100}
    assert {request[1].strike for request in app.market_data_requests} == {95, 100}
    assert set(quotes) == {
        (95, "C"),
        (95, "P"),
        (100, "C"),
        (100, "P"),
    }


def test_ib_chain_provider_skips_invalid_exact_option_contracts():
    app = InvalidExactOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.01,
    )

    contracts = provider.fetch_chain_contracts(
        "hims",
        "2026-07-24",
        [95, 100, 105],
    )

    assert {contract.strike for contract in contracts} == {95, 100}
    assert app.request_errors_by_req_id == {}


def test_ib_chain_provider_rejects_invalid_underlying_from_broad_request():
    app = InvalidBroadOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(app)

    with pytest.raises(OptionsDataUnavailable, match="Invalid ticker: NOPE."):
        provider.fetch_chain_contracts(
            "nope",
            "2026-06-19",
            [100],
        )


def test_ib_chain_provider_omits_unresolved_expiration_strikes():
    app = FakeOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(app)

    contracts = provider.fetch_chain_contracts(
        "hims",
        "2026-06-19",
        [95, 100, 105],
    )
    quotes = provider.fetch_chain_quotes(contracts)

    requested_contracts = [request[1] for request in app.market_data_requests]
    assert {contract.strike for contract in contracts} == {95, 100}
    assert {contract.strike for contract in requested_contracts} == {95, 100}
    assert set(quotes) == {
        (95, "C"),
        (95, "P"),
        (100, "C"),
        (100, "P"),
    }


def test_ib_chain_provider_waits_for_ticks_after_the_first_callback():
    app = SlowOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(
        app,
        timeout_seconds=0.05,
    )

    contracts = provider.fetch_chain_contracts(
        "aapl",
        "2026-06-19",
        [100],
    )
    quotes = provider.fetch_chain_quotes(contracts)

    assert quotes[(100, "C")].mid == 1.2
    assert quotes[(100, "P")].mid == 1.2


def test_ib_chain_stream_provider_cancels_subscriptions_on_close():
    app = FakeOptionChainIbApp()
    provider = IbOptionChainStreamProvider(app, wait_seconds=0.01)
    stop_event = threading.Event()
    contracts = IbOptionChainSnapshotProvider(app).fetch_chain_contracts(
        "aapl",
        "2026-06-19",
        [100],
    )
    stream = provider.stream_chain_quotes(
        contracts,
        stop_event,
    )

    key, quote = next(stream)
    stop_event.set()
    stream.close()

    requested_contracts = [request[1] for request in app.market_data_requests]
    assert key == (100, "C")
    assert quote.mid == 1.2
    assert len(requested_contracts) == 2
    assert all(request[3] is False for request in app.market_data_requests)
    assert app.cancelled_market_data == [90_000, 90_001]
    assert app.option_market_req_to_key == {}
    assert app.option_market_data == {}


def test_ib_chain_stream_provider_isolates_overlapping_stream_state():
    app = FakeOptionChainIbApp()
    provider = IbOptionChainStreamProvider(app, wait_seconds=0.01)
    first_stop_event = threading.Event()
    second_stop_event = threading.Event()
    first_contracts = IbOptionChainSnapshotProvider(app).fetch_chain_contracts(
        "aapl",
        "2026-06-19",
        [100],
    )
    second_contracts = IbOptionChainSnapshotProvider(app).fetch_chain_contracts(
        "msft",
        "2026-06-19",
        [100],
    )
    first_stream = provider.stream_chain_quotes(
        first_contracts,
        first_stop_event,
    )
    second_stream = provider.stream_chain_quotes(
        second_contracts,
        second_stop_event,
    )

    first_key, first_quote = next(first_stream)
    second_key, second_quote = next(second_stream)
    first_stream.close()

    assert first_key == (100, "C")
    assert first_quote.bid == 1
    assert second_key == (100, "C")
    assert second_quote.bid == 1
    assert app.cancelled_market_data == [90_000, 90_001]
    assert app.option_market_req_to_key == {
        90_002: (100, "C"),
        90_003: (100, "P"),
    }
    assert set(app.option_market_data) == {90_002, 90_003}

    second_stream.close()

    assert app.cancelled_market_data == [90_000, 90_001, 90_002, 90_003]
    assert app.option_market_req_to_key == {}
    assert app.option_market_data == {}
