import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.ib.portfolio import AnalysisMarketData
from app.portfolio_analysis.beta import ResolvedBeta
from app.portfolio_analysis.service import PortfolioAnalysisService
from app.portfolio.service import empty_portfolio_response
from app.schemas import PortfolioAccountSummary, PortfolioPosition, PortfolioResponse
from tests.conftest import FakePortfolioClient, make_api


def connected_client(**kwargs) -> FakePortfolioClient:
    client = FakePortfolioClient(connected=True, block_refresh=True, **kwargs)
    client.analysis_market_data = AnalysisMarketData(
        by_con_id={},
        underlyings={"AAPL": {"last": 200.0}},
    )
    return client


def test_analysis_websocket_streams_each_refresh_and_releases_the_viewer():
    portfolio_client = connected_client()
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with client.websocket_connect("/portfolio/analysis/ws") as websocket:
            cached = websocket.receive_json()
            viewers_while_open = portfolio_client.analysis_viewers
            portfolio_client.allow_refresh.set()
            refreshed = websocket.receive_json()
        viewers_after_close = portfolio_client.analysis_viewers

    assert viewers_while_open == 1
    assert viewers_after_close == 0
    assert portfolio_client.quote_viewers == 0
    assert cached["account"] is None
    assert cached["underlyings"] == []
    assert cached["message"] == "Portfolio data has not loaded yet."

    assert refreshed["account"] == "DU1234567"
    assert refreshed["accounts"] == ["DU1234567"]
    summary = refreshed["summary"]
    assert summary["net_liquidation"] == 125_000
    assert summary["net_dollar_delta"] == 20_000
    assert summary["beta_weighted_delta_multiple"] == pytest.approx(0.16)
    assert summary["margin_utilisation_percent"] == pytest.approx(6.4)
    assert summary["excess_liquidity"] == 117_000
    assert summary["largest_underlying"] == "AAPL"
    assert summary["coverage"]["fallback_beta"] == 1
    [aapl] = refreshed["underlyings"]
    assert (aapl["symbol"], aapl["beta"], aapl["beta_source"]) == ("AAPL", 1.0, "fallback")
    assert aapl["groups"][0]["kind"] == "stock"
    assert aapl["groups"][0]["max_loss"] == 18_250
    stress = refreshed["stress"]
    assert (len(stress["cells"]), len(stress["realistic_path"]), stress["legs"]) == (32, 4, 1)
    down_10 = next(
        cell
        for cell in stress["cells"]
        if cell["spy_move_percent"] == pytest.approx(-10) and cell["iv_shock_percent"] == 0
    )
    assert down_10["pnl"] == pytest.approx(-2_000)
    assert down_10["pnl_percent"] == pytest.approx(-1.6)
    margin = stress["margin"]
    # 25% x 100 shares x $200 against IB's $8,000.
    assert margin["model_margin"] == pytest.approx(5_000)
    assert margin["calibration_factor"] == pytest.approx(1.6)
    assert down_10["excess_liquidity"] == pytest.approx(125_000 - 2_000 - 1.6 * 4_500)
    assert margin["margin_call_beyond_path"] is True


def test_analysis_viewers_are_counted_per_websocket():
    portfolio_client = connected_client()
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with client.websocket_connect("/portfolio/analysis/ws") as first:
            first.receive_json()
            with client.websocket_connect("/portfolio/analysis/ws") as second:
                second.receive_json()
                both_open = portfolio_client.analysis_viewers
            one_open = portfolio_client.analysis_viewers
        portfolio_client.allow_refresh.set()

    assert (both_open, one_open, portfolio_client.analysis_viewers) == (2, 1, 0)


def test_analysis_websocket_switches_account_and_ignores_bad_messages():
    portfolio_client = connected_client()
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with client.websocket_connect("/portfolio/analysis/ws?account=DU1234567") as websocket:
            websocket.receive_json()
            portfolio_client.allow_refresh.set()
            websocket.receive_json()
            websocket.send_text("not json")
            websocket.send_json({"account": "UNKNOWN"})
            switched = websocket.receive_json()

    # An unknown account falls back to the first account in the snapshot.
    assert switched["account"] == "DU1234567"
    assert switched["summary"]["net_dollar_delta"] == 20_000
    assert portfolio_client.analysis_viewers == 0


def test_analysis_get_uses_the_cached_snapshot():
    portfolio_client = FakePortfolioClient(connected=False)
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        response = client.get("/portfolio/analysis", params={"account": "DU1234567"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["connected"] is False
    assert body["underlyings"] == []
    assert body["message"] == "Interactive Brokers is not connected."
    assert portfolio_client.analysis_viewers == 0


def test_slow_analysis_does_not_block_the_portfolio_refresh():
    portfolio_client = connected_client()
    api = make_api(portfolio_client)
    release = threading.Event()
    analysis_started = threading.Event()

    with TestClient(api) as client:
        service = api.state.portfolio_analysis_service
        build = service.build

        def slow_build(snapshot, account=None):
            analysis_started.set()
            release.wait(timeout=5)
            return build(snapshot, account)

        service.build = slow_build
        try:
            with client.websocket_connect("/portfolio/analysis/ws") as analysis_ws:
                assert analysis_started.wait(timeout=1)
                with client.websocket_connect("/portfolio/ws") as portfolio_ws:
                    portfolio_ws.receive_json()
                    portfolio_client.allow_refresh.set()
                    refreshed = portfolio_ws.receive_json()
                refreshed_while_blocked = not release.is_set()
                release.set()
                analysis_ws.receive_json()
        finally:
            release.set()

    assert refreshed_while_blocked
    assert refreshed["positions"][0]["symbol"] == "AAPL"
    assert portfolio_client.analysis_viewers == 0


class BlockingBetaService:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.computed = threading.Event()
        self.betas: dict[str, ResolvedBeta] = {}
        self.compute_calls: list[list[str]] = []

    def resolve(self, tickers, *, compute=True):
        tickers = sorted(tickers)
        if compute:
            self.compute_calls.append(tickers)
            self.release.wait(timeout=5)
            self.betas = {ticker: ResolvedBeta(ticker, 1.4, "computed", 252) for ticker in tickers}
            self.computed.set()
        return {
            ticker: self.betas.get(ticker, ResolvedBeta(ticker, 1.0, "fallback", 0, pending=True))
            for ticker in tickers
        }

    def benchmark_bars(self, *, compute=True):
        return []


def aapl_snapshot(portfolio_client) -> PortfolioResponse:
    return PortfolioResponse(
        status=portfolio_client.get_status(),
        accounts=[PortfolioAccountSummary(account="DU1234567", net_liquidation=100_000)],
        positions=[
            PortfolioPosition(
                account="DU1234567",
                symbol="AAPL",
                sec_type="STK",
                exchange="NASDAQ",
                currency="USD",
                quantity=100,
                last_price=200,
            )
        ],
    )


def test_missing_betas_resolve_in_the_background():
    portfolio_client = connected_client()
    beta_service = BlockingBetaService()
    service = PortfolioAnalysisService(
        portfolio_client,
        beta_service,
        risk_free_rate=0.04,
        now=lambda: datetime(2026, 9, 28, 14, tzinfo=UTC),
    )
    snapshot = aapl_snapshot(portfolio_client)

    first = service.build(snapshot)
    second = service.build(snapshot)
    beta_service.release.set()
    assert beta_service.computed.wait(timeout=1)
    service.beta_thread.join(timeout=1)
    third = service.build(snapshot)

    assert first.underlyings[0].beta_source == "fallback"
    assert second.underlyings[0].beta_source == "fallback"
    # Only one background fetch runs at a time.
    assert beta_service.compute_calls == [["AAPL"]]
    assert (third.underlyings[0].beta, third.underlyings[0].beta_source) == (1.4, "computed")
    assert third.summary.beta_weighted_delta == pytest.approx(20_000 * 1.4)


def test_cached_fallback_betas_start_no_background_fetch():
    portfolio_client = connected_client()
    beta_service = BlockingBetaService()
    beta_service.betas = {"AAPL": ResolvedBeta("AAPL", 1.0, "fallback", 12)}
    service = PortfolioAnalysisService(portfolio_client, beta_service, risk_free_rate=0.04)

    result = service.build(aapl_snapshot(portfolio_client))

    assert result.underlyings[0].beta_source == "fallback"
    assert service.beta_thread is None


def test_disconnected_snapshot_builds_an_empty_analysis():
    portfolio_client = FakePortfolioClient(connected=False)
    service = PortfolioAnalysisService(
        portfolio_client,
        BlockingBetaService(),
        risk_free_rate=0.04,
    )
    result = service.build(empty_portfolio_response(portfolio_client.get_status()), "U1")

    assert result.account is None
    assert result.accounts == []
    assert result.message == "Interactive Brokers is not connected."
    assert result.stress is None
