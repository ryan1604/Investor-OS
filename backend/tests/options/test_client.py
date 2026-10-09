import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import (
    date,
    timedelta,
)

import pytest

from app.options.client import (
    AnalysisUnderlyingPriceCache,
    CachedOptionMetadataProvider,
    OptionsClient,
)
from app.options.types import (
    ContractLookupPriority,
    OptionChainContractHydration,
    OptionChainStreamNotice,
    OptionsDataUnavailable,
    ScannerOptionContract,
)
from app.options.rotation import capped_chain_strikes
from app.options.domain import (
    OptionMetadata,
    chunk_date_range,
    option_chain_rows,
    option_chain_strikes,
    to_option_quote,
)
from app.options.store import CompletedDailyBar, OptionsDailyBarStore
from app.schemas import OptionQuote
from tests.conftest import wait_until


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

    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: threading.Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority=None,
    ) -> OptionChainContractHydration:
        return OptionChainContractHydration(
            contracts=self.fetch_chain_contracts(ticker, expiration, strikes),
        )

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


class RecoveringPartialChainProvider(FakeChainProvider):
    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: threading.Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority=None,
    ) -> OptionChainContractHydration:
        self.requests.append((ticker, expiration, strikes))
        timed_out_strikes = (
            frozenset({95})
            if 95 in strikes and len(self.requests) == 1
            else frozenset()
        )
        resolved_strikes = [
            strike for strike in strikes if strike not in timed_out_strikes
        ]
        contracts = FakeChainProvider(
            contract_strikes=resolved_strikes
        ).fetch_chain_contracts(ticker, expiration, resolved_strikes)
        return OptionChainContractHydration(
            contracts=contracts,
            timed_out_strikes=timed_out_strikes,
        )


class BlockingHydrationChainProvider(FakeChainProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.received_stop_event: threading.Event | None = None

    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: threading.Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority=None,
    ) -> OptionChainContractHydration:
        self.requests.append((ticker, expiration, strikes))
        self.received_stop_event = stop_event
        self.started.set()
        if stop_event is not None:
            stop_event.wait(timeout=1)
        return OptionChainContractHydration(
            contracts=[],
            timed_out_strikes=frozenset(strikes),
        )


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
        super().__init__()
        super().__init__()
        super().__init__()
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


def test_option_metadata_cache_reuses_expirations_and_strikes():
    provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[95, 100, 105],
    )
    cache = CachedOptionMetadataProvider(provider)

    first_metadata = cache.fetch_option_metadata(" aapl ")
    metadata = cache.fetch_option_metadata("AAPL")

    assert first_metadata.expirations == ["2026-06-19"]
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


def test_option_metadata_cache_does_not_hold_other_tickers_behind_a_slow_fetch():
    release_slow = threading.Event()

    class SlowForAaplProvider(FakeMetadataProvider):
        def fetch_option_metadata(self, ticker):
            if ticker == "AAPL":
                release_slow.wait(timeout=2)
            return super().fetch_option_metadata(ticker)

    cache = CachedOptionMetadataProvider(SlowForAaplProvider(strikes=[100]))
    slow = threading.Thread(target=cache.fetch_option_metadata, args=("AAPL",))
    slow.start()
    wait_until(lambda: slow.is_alive())

    try:
        assert cache.fetch_option_metadata("MSFT").strikes == [100]
        assert slow.is_alive()
    finally:
        release_slow.set()
        slow.join()


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
        batches: list[list[tuple[tuple[float, str], OptionQuote]]] | None = None,
    ) -> None:
        self.batches = batches or []
        self.requests: list[tuple[str, str, list[float]]] = []

    def stream_chain_quotes(self, contracts, stop_event, rotation=None):
        self.rotation = rotation
        first_contract = contracts[0] if contracts else None
        ticker = first_contract.ticker if first_contract else ""
        expiration = first_contract.expiration if first_contract else ""
        strikes = sorted({contract.strike for contract in contracts})
        self.requests.append((ticker, expiration, strikes))

        for batch in self.batches:
            if stop_event.is_set():
                break
            filtered_batch = [
                (key, quote) for key, quote in batch if key[0] in strikes
            ]
            if filtered_batch:
                yield filtered_batch


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
            max_chain_stream_strikes=80,
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


def test_get_expirations_prefetches_once_concurrent_analysis_caches_the_price(
    tmp_path,
):
    strikes = list(range(50, 151))
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=strikes,
    )
    chain_provider = FallbackRecordingChainProvider(contract_strikes=strikes)
    client, _store = make_client(
        tmp_path,
        FakeHistoricalProvider(),
        metadata_provider,
        chain_provider,
    )

    response = client.get_expirations("AAPL", current_date=date(2026, 5, 30))
    assert chain_provider.requests == []
    client.analysis_underlying_price_cache.set("AAPL", 99.6)

    wait_until(lambda: len(chain_provider.requests) == 1)
    client.shutdown()

    assert response.selected_expiration == "2026-06-19"
    assert len(chain_provider.fallback_strikes[0]) == client.chain_fallback_strike_count


def test_get_expirations_prefetch_without_a_price_skips_exact_fallback(tmp_path):
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[90, 100, 110],
    )
    chain_provider = FallbackRecordingChainProvider(contract_strikes=[90, 100, 110])
    client, _store = make_client(
        tmp_path,
        FakeHistoricalProvider(),
        metadata_provider,
        chain_provider,
    )
    client.chain_prefetch_price_wait_seconds = 0.05

    client.get_expirations("AAPL", current_date=date(2026, 5, 30))

    wait_until(lambda: len(chain_provider.requests) == 1)
    client.shutdown()

    assert chain_provider.fallback_strikes == [[]]


def test_prefetch_lookups_yield_until_someone_opens_that_chain(tmp_path):
    metadata_provider = FakeMetadataProvider(
        expirations=["2026-06-19"],
        strikes=[90, 100, 110],
    )
    chain_provider = PriorityRecordingChainProvider(contract_strikes=[90, 100, 110])
    client, _store = make_client(
        tmp_path,
        FakeHistoricalProvider(),
        metadata_provider,
        chain_provider,
    )
    client.chain_prefetch_price_wait_seconds = 0.05

    client.get_expirations("AAPL", current_date=date(2026, 5, 30))
    wait_until(lambda: len(chain_provider.priorities) == 1)
    prefetch_priority = chain_provider.priorities[0]
    assert prefetch_priority.is_background()

    opener = threading.Thread(
        target=client.chain_contracts,
        args=("AAPL", "2026-06-19", [90, 100, 110]),
        kwargs={"cacheable": True},
    )
    opener.start()
    wait_until(lambda: not prefetch_priority.is_background())
    chain_provider.release.set()
    opener.join()
    client.shutdown()

    assert len(chain_provider.priorities) == 1


def test_analysis_price_cache_wait_returns_when_the_price_is_set():
    cache = AnalysisUnderlyingPriceCache()
    threading.Timer(0.02, cache.set, args=("AAPL", 101.5)).start()

    assert cache.wait("aapl", 1) == 101.5
    assert AnalysisUnderlyingPriceCache().wait("AAPL", 0.01) is None


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


def test_get_chain_returns_delta_bounded_call_and_put_rows(tmp_path):
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
        ("AAPL", "2026-06-19", [50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]),
    ]


def test_get_chain_requests_strikes_beyond_thirty_percent_of_underlying(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(
        strikes=[45, 38, 0, 39, 20, 45, -1, 30],
    )
    chain_provider = FakeChainProvider(contract_strikes=[20, 30, 38, 39, 45])
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )
    client.analysis_underlying_price_cache.set("HIMS", 29.79)

    response = client.get_chain(
        "HIMS",
        "2026-08-28",
        current_date=date(2026, 7, 28),
    )

    assert response.underlying_price == 29.79
    assert chain_provider.requests == [
        ("HIMS", "2026-08-28", [20, 30, 38, 39, 45]),
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


def test_get_chain_retries_only_timed_out_strikes_and_keeps_resolved_contracts(
    tmp_path,
):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100])
    chain_provider = RecoveringPartialChainProvider(
        {
            (90, "P"): OptionQuote(delta=-0.2, bid=1),
            (95, "C"): OptionQuote(delta=0.5, bid=1),
            (95, "P"): OptionQuote(delta=-0.5, bid=1),
            (100, "C"): OptionQuote(delta=0.2, bid=1),
        }
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
    second_response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )
    third_response = client.get_chain(
        "AAPL",
        "2026-06-19",
        current_date=date(2026, 5, 30),
    )

    assert [row.strike for row in first_response.rows] == [90, 100]
    assert [row.strike for row in second_response.rows] == [90, 95, 100]
    assert [row.strike for row in third_response.rows] == [90, 95, 100]
    assert chain_provider.requests == [
        ("AAPL", "2026-06-19", [90, 95, 100]),
        ("AAPL", "2026-06-19", [95]),
    ]
    assert client.contract_cache_in_flight == {}


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
        [[((100, "C"), OptionQuote(delta=0.25, bid=2))]],
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


def test_option_chain_strikes_keeps_all_positive_unique_strikes():
    assert option_chain_strikes([45, 38, 0, 39, 20, 45, -1, 30]) == [
        20,
        30,
        38,
        39,
        45,
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


def test_stream_chain_cancels_contract_hydration_before_first_snapshot(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[95, 100])
    chain_provider = BlockingHydrationChainProvider()
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_provider,
    )
    client.analysis_underlying_price_cache.set("MSFT", 100)
    stop_event = threading.Event()
    stream = client.stream_chain(
        "MSFT",
        "2026-06-19",
        stop_event=stop_event,
        current_date=date(2026, 5, 30),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_message = executor.submit(next, stream)
        assert chain_provider.started.wait(timeout=1)
        stop_event.set()
        with pytest.raises(StopIteration):
            first_message.result(timeout=0.5)

    assert chain_provider.received_stop_event is stop_event


def test_stream_chain_yields_snapshot_then_row_updates(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 100, 110])
    chain_stream_provider = FakeChainStreamProvider(
        [
            [
                ((100, "C"), OptionQuote(delta=None, bid=1, ask=1.2, mid=1.1)),
                ((100, "P"), OptionQuote(delta=None, bid=0.8, ask=1, mid=0.9)),
            ],
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
    assert messages[1].row.put is not None
    assert messages[1].row.put.bid == 0.8
    assert len(messages) == 2
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
        [[((100, "C"), OptionQuote(delta=0.5, bid=2))]]
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


def test_stream_chain_snapshots_every_delta_bound_change(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100, 105, 110])
    chain_stream_provider = FakeChainStreamProvider(
        [
            [
                ((90, "P"), OptionQuote(delta=-0.1, bid=1)),
                ((100, "C"), OptionQuote(delta=0.1, bid=1)),
                ((105, "C"), OptionQuote(delta=0.08, bid=1)),
            ],
            [((110, "C"), OptionQuote(delta=0.2, bid=1))],
            [((110, "C"), OptionQuote(delta=0.05, bid=1))],
            [((100, "C"), OptionQuote(delta=0.05, bid=2))],
            [((100, "C"), OptionQuote(delta=0.1, bid=3))],
            [((100, "C"), OptionQuote(delta=0.1, bid=4))],
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

    assert [message.type for message in messages] == [
        "snapshot",
        "snapshot",
        "snapshot",
        "snapshot",
        "snapshot",
        "snapshot",
        "update",
    ]
    assert [row.strike for row in messages[1].rows or []] == [90, 95, 100]
    assert [row.strike for row in messages[2].rows or []] == [
        90,
        95,
        100,
        105,
        110,
    ]
    assert [row.strike for row in messages[3].rows or []] == [90, 95, 100]
    assert [row.strike for row in messages[4].rows or []] == [90, 100, 105, 110]
    assert [row.strike for row in messages[5].rows or []] == [90, 95, 100]
    assert messages[6].row is not None
    assert messages[6].row.strike == 100
    assert messages[6].row.call is not None
    assert messages[6].row.call.bid == 4


def test_stream_chain_streams_nearest_strikes_and_rotates_the_rest(tmp_path):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100, 105, 110])
    chain_stream_provider = FakeChainStreamProvider(
        [
            [
                ((90, "C"), OptionQuote(delta=0.2, bid=1)),
                ((90, "P"), OptionQuote(delta=-0.2, bid=1)),
                ((95, "C"), OptionQuote(delta=0.2, bid=2)),
                ((95, "P"), OptionQuote(delta=-0.2, bid=1)),
                ((100, "C"), OptionQuote(delta=0.2, bid=3)),
            ],
        ]
    )
    client, _store = make_client(
        tmp_path,
        provider,
        metadata_provider,
        chain_stream_provider=chain_stream_provider,
    )
    client.max_chain_strikes = 4
    client.max_chain_stream_strikes = 2

    messages = list(
        client.stream_chain(
            "msft",
            "2026-06-19",
            stop_event=threading.Event(),
            current_date=date(2026, 5, 30),
        )
    )

    assert messages[0].message == "Streaming 4 strike(s) for MSFT 2026-06-19."
    assert messages[0].rows == []
    assert chain_stream_provider.requests == [
        ("MSFT", "2026-06-19", [95, 100]),
    ]
    rotation = chain_stream_provider.rotation
    assert rotation.display_strikes == [90, 95, 100, 105]
    assert {contract.strike for contract in rotation.next_batch(10)} == {90, 105}


def test_stream_chain_streams_nearest_contracts_first_and_forwards_warnings(
    tmp_path,
):
    provider = FakeHistoricalProvider()
    metadata_provider = FakeMetadataProvider(strikes=[90, 95, 100, 105, 110])
    chain_stream_provider = NoticeChainStreamProvider(
        [
            OptionChainStreamNotice(warning="Waiting for free IB lines."),
            [((100, "C"), OptionQuote(delta=0.5, bid=1))],
            OptionChainStreamNotice(warning=None),
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

    assert [contract.strike for contract in chain_stream_provider.contracts][:4] == [
        100,
        100,
        95,
        95,
    ]
    assert [(message.type, message.warning) for message in messages] == [
        ("snapshot", None),
        ("snapshot", "Waiting for free IB lines."),
        ("snapshot", "Waiting for free IB lines."),
        ("snapshot", None),
    ]


class NoticeChainStreamProvider:
    def __init__(self, items) -> None:
        self.items = items
        self.contracts = []

    def stream_chain_quotes(self, contracts, stop_event, rotation=None):
        self.contracts = contracts
        yield from self.items


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


def test_chain_contracts_limit_fallback_to_strikes_nearest_the_price(tmp_path):
    strikes = list(range(50, 151))
    chain_provider = FallbackRecordingChainProvider(contract_strikes=strikes)
    client, _store = make_client(
        tmp_path,
        FakeHistoricalProvider(),
        FakeMetadataProvider(strikes=strikes),
        chain_provider,
    )
    client.analysis_underlying_price_cache.set("AAPL", 99.6)

    client.get_chain("AAPL", "2026-06-19", current_date=date(2026, 5, 30))

    nearest = sorted(strikes, key=lambda strike: (abs(strike - 99.6), strike))
    assert chain_provider.fallback_strikes == [
        sorted(nearest[: client.chain_fallback_strike_count])
    ]
    assert client.chain_fallback_strike_count < len(strikes)


def test_chain_skips_fallback_skipped_strikes_until_they_near_the_price(tmp_path):
    chain_provider = SkippingChainProvider(contract_strikes=[90, 95, 100, 105])
    client, _store = make_client(
        tmp_path,
        FakeHistoricalProvider(),
        FakeMetadataProvider(strikes=[90, 95, 100, 105]),
        chain_provider,
    )
    client.chain_fallback_strike_count = 2
    client.analysis_underlying_price_cache.set("AAPL", 97)

    first = client.chain_context("AAPL", "2026-06-19")
    second = client.chain_context("AAPL", "2026-06-19")
    client.analysis_underlying_price_cache.set("AAPL", 104)
    third = client.chain_context("AAPL", "2026-06-19")

    assert first.strikes == [95, 100]
    assert second.strikes == [95, 100]
    assert third.strikes == [95, 100, 105]
    assert chain_provider.hydration_requests == [
        ("AAPL", "2026-06-19", [90, 95, 100, 105]),
        ("AAPL", "2026-06-19", [105]),
    ]


class FallbackRecordingChainProvider(FakeChainProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.fallback_strikes: list[list[float] | None] = []

    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: threading.Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority=None,
    ) -> OptionChainContractHydration:
        self.fallback_strikes.append(fallback_strikes)
        return super().fetch_chain_contract_hydration(
            ticker,
            expiration,
            strikes,
            stop_event,
            fallback_strikes,
            resolved_keys,
        )


class PriorityRecordingChainProvider(FakeChainProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.priorities: list[ContractLookupPriority | None] = []
        self.release = threading.Event()

    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: threading.Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority=None,
    ) -> OptionChainContractHydration:
        self.priorities.append(priority)
        self.release.wait(timeout=2)
        return super().fetch_chain_contract_hydration(ticker, expiration, strikes)


class SkippingChainProvider(FakeChainProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hydration_requests: list[tuple[str, str, list[float]]] = []

    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: threading.Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority=None,
    ) -> OptionChainContractHydration:
        self.hydration_requests.append((ticker, expiration, strikes))
        resolved = [strike for strike in strikes if strike in (fallback_strikes or [])]
        return OptionChainContractHydration(
            contracts=self.fetch_chain_contracts(ticker, expiration, resolved),
            skipped_strikes=frozenset(strikes) - frozenset(resolved),
        )