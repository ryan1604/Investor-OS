from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.portfolio_analysis.service import PortfolioAnalysisService, risk_snapshot
from app.sessions import snapshot_session
from app.portfolio_analysis.snapshot_store import RiskSnapshotStore
from app.schemas import (
    AnalysisCoverage,
    AnalysisGroup,
    AnalysisLeg,
    AnalysisMarginEstimate,
    AnalysisRiskSnapshot,
    AnalysisStressCell,
    AnalysisStressGrid,
    AnalysisSummary,
    AnalysisUnderlying,
    PortfolioAnalysisResponse,
)
from tests.conftest import Clock, FakePortfolioClient, make_api
from tests.portfolio_analysis.test_api import BlockingBetaService, connected_client

NEW_YORK = ZoneInfo("America/New_York")
# A viewer connected long enough ago to be past the warm-up.
WARM_VIEWER = datetime(2026, 1, 1, tzinfo=UTC)


def ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=NEW_YORK)


# 2026-09-25 is a Friday; 2026-09-28 is a Monday.
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (ny(2026, 9, 29, 9, 29), (date(2026, 9, 28), "post_close")),
        (ny(2026, 9, 29, 9, 30), (date(2026, 9, 29), "intraday")),
        (ny(2026, 9, 29, 15, 59, 59), (date(2026, 9, 29), "intraday")),
        (ny(2026, 9, 29, 16, 0), (date(2026, 9, 29), "post_close")),
        (ny(2026, 9, 29, 23, 59), (date(2026, 9, 29), "post_close")),
        (ny(2026, 9, 25, 17, 0), (date(2026, 9, 25), "post_close")),
        (ny(2026, 9, 26, 12, 0), (date(2026, 9, 25), "post_close")),
        (ny(2026, 9, 27, 20, 0), (date(2026, 9, 25), "post_close")),
        (ny(2026, 9, 28, 8, 0), (date(2026, 9, 25), "post_close")),
        (ny(2026, 9, 28, 0, 0), (date(2026, 9, 25), "post_close")),
    ],
)
def test_snapshot_session_keys_across_open_close_and_weekends(now, expected):
    assert snapshot_session(now) == expected


def test_snapshot_session_uses_new_york_time_for_utc_input():
    # 20:30 UTC is 16:30 in New York (EDT): after the close.
    assert snapshot_session(datetime(2026, 9, 29, 20, 30, tzinfo=UTC)) == (
        date(2026, 9, 29),
        "post_close",
    )
    # 14:00 UTC is 09:00 EST in winter: before the open.
    assert snapshot_session(datetime(2026, 12, 1, 14, 0, tzinfo=UTC)) == (
        date(2026, 11, 30),
        "post_close",
    )


def snapshot(kind: str, theta: float, session: date = date(2026, 9, 29)) -> AnalysisRiskSnapshot:
    return AnalysisRiskSnapshot(
        session_date=session,
        kind=kind,
        captured_at=datetime(2026, 9, 29, 15, tzinfo=UTC),
        net_liquidation=100_000,
        net_theta=theta,
    )


def test_store_precedence_keeps_post_close_over_intraday(tmp_path):
    store = RiskSnapshotStore(tmp_path / "analysis.sqlite3")

    assert store.save("U1", snapshot("intraday", 1))
    assert store.save("U1", snapshot("intraday", 2))
    assert [(row.kind, row.net_theta) for row in store.history("U1")] == [("intraday", 2)]

    assert store.save("U1", snapshot("post_close", 3))
    assert not store.save("U1", snapshot("intraday", 4))
    assert [(row.kind, row.net_theta) for row in store.history("U1")] == [("post_close", 3)]

    # A later post-close view replaces an earlier one.
    assert store.save("U1", snapshot("post_close", 5))
    assert [(row.kind, row.net_theta) for row in store.history("U1")] == [("post_close", 5)]


def test_store_keeps_one_row_per_account_and_session_in_date_order(tmp_path):
    store = RiskSnapshotStore(tmp_path / "analysis.sqlite3")
    store.save("U1", snapshot("post_close", 2, date(2026, 9, 29)))
    store.save("U1", snapshot("post_close", 1, date(2026, 9, 25)))
    store.save("U2", snapshot("intraday", 9, date(2026, 9, 29)))

    history = RiskSnapshotStore(tmp_path / "analysis.sqlite3").history("U1")

    assert [(row.session_date, row.net_theta) for row in history] == [
        (date(2026, 9, 25), 1),
        (date(2026, 9, 29), 2),
    ]
    assert history[0].net_liquidation == 100_000
    assert history[0].captured_at == datetime(2026, 9, 29, 15, tzinfo=UTC)
    assert [row.kind for row in store.history("U2")] == ["intraday"]
    assert store.history("U3") == []


def analysis(
    account: str | None = "U1",
    *,
    connected=True,
    net_liquidation=100_000.0,
    flags: tuple[str, ...] = (),
):
    leg = AnalysisLeg(
        symbol="AAPL", sec_type="STK", currency="USD", quantity=100, price=200, flags=list(flags)
    )
    return PortfolioAnalysisResponse(
        status=FakePortfolioClient(connected=connected).get_status(),
        account=account,
        as_of=datetime(2026, 9, 29, 15, tzinfo=UTC),
        summary=AnalysisSummary(
            net_liquidation=net_liquidation,
            beta_weighted_delta=45_000,
            beta_weighted_delta_multiple=0.45,
            net_theta=80,
            assignment_exposure_percent=12,
            margin_utilisation_percent=20,
            largest_underlying="AAPL",
            largest_underlying_percent=30,
            coverage=AnalysisCoverage(positions=1, missing_price=int("missing_price" in flags)),
        ),
        underlyings=[
            AnalysisUnderlying(
                symbol="AAPL",
                beta=1.0,
                beta_source="computed",
                groups=[AnalysisGroup(kind="stock", label="Stock", quantity=100, legs=[leg])],
            )
        ],
        stress=AnalysisStressGrid(
            spy_moves_percent=[],
            iv_shocks_percent=[],
            realistic_path=[
                AnalysisStressCell(spy_move_percent=-10, iv_shock_percent=40, pnl=-5_000),
                AnalysisStressCell(
                    spy_move_percent=-20,
                    iv_shock_percent=80,
                    pnl=-15_000,
                    pnl_percent=-15,
                ),
            ],
            margin=AnalysisMarginEstimate(
                model_margin=18_000,
                calibration_factor=1.1,
                distance_to_margin_call_percent=22.5,
            ),
        ),
    )


def recording_service(tmp_path, clock: Clock) -> PortfolioAnalysisService:
    return PortfolioAnalysisService(
        FakePortfolioClient(connected=True),
        BlockingBetaService(),
        risk_free_rate=0.04,
        snapshot_store=RiskSnapshotStore(tmp_path / "analysis.sqlite3"),
        now=clock,
    )


def test_risk_snapshot_copies_account_metrics():
    result = risk_snapshot(analysis(), ny(2026, 9, 29, 17, 0))

    assert (result.session_date, result.kind) == (date(2026, 9, 29), "post_close")
    assert result.captured_at == ny(2026, 9, 29, 17, 0)
    assert result.beta_weighted_delta_multiple == 0.45
    assert result.net_theta == 80
    assert result.assignment_exposure_percent == 12
    assert result.margin_utilisation_percent == 20
    assert (result.largest_underlying, result.largest_underlying_percent) == ("AAPL", 30)
    assert (result.realistic_down_20_pnl, result.realistic_down_20_pnl_percent) == (-15_000, -15)
    assert (result.model_margin, result.calibration_factor) == (18_000, 1.1)
    assert result.distance_to_margin_call_percent == 22.5
    assert result.margin_call_beyond_path is False

    no_grid = risk_snapshot(analysis().model_copy(update={"stress": None}), ny(2026, 9, 29, 17))
    assert no_grid.realistic_down_20_pnl is None
    assert no_grid.model_margin is None


def test_recording_is_throttled_to_once_per_minute_per_account(tmp_path):
    clock = Clock(ny(2026, 9, 29, 11, 0))
    service = recording_service(tmp_path, clock)

    assert service.record_snapshot(analysis(net_liquidation=100_000), WARM_VIEWER)
    clock.now += timedelta(seconds=59)
    assert not service.record_snapshot(analysis(net_liquidation=101_000), WARM_VIEWER)
    # Another account has its own minute.
    assert service.record_snapshot(analysis("U2"), WARM_VIEWER)
    clock.now += timedelta(seconds=1)
    assert service.record_snapshot(analysis(net_liquidation=102_000), WARM_VIEWER)

    [row] = service.snapshot_store.history("U1")
    assert (row.kind, row.net_liquidation, row.captured_at) == (
        "intraday",
        102_000,
        ny(2026, 9, 29, 11, 1),
    )


def test_intraday_views_never_replace_the_post_close_snapshot(tmp_path):
    clock = Clock(ny(2026, 9, 29, 11, 0))
    clock.now = ny(2026, 9, 29, 8, 0)
    service = recording_service(tmp_path, clock)

    assert service.record_snapshot(analysis(net_liquidation=100_000), WARM_VIEWER)
    clock.now = ny(2026, 9, 29, 10, 0)
    assert service.record_snapshot(analysis(net_liquidation=105_000), WARM_VIEWER)
    clock.now = ny(2026, 9, 29, 16, 30)
    assert service.record_snapshot(analysis(net_liquidation=110_000), WARM_VIEWER)
    clock.now = ny(2026, 9, 29, 16, 31)
    assert service.record_snapshot(analysis(net_liquidation=111_000), WARM_VIEWER)

    history = service.snapshot_store.history("U1")
    assert [(row.session_date, row.kind, row.net_liquidation) for row in history] == [
        (date(2026, 9, 28), "post_close", 100_000),
        (date(2026, 9, 29), "post_close", 111_000),
    ]


def test_no_snapshot_until_the_viewer_has_warmed_up(tmp_path):
    clock = Clock(ny(2026, 9, 29, 11, 0))
    service = recording_service(tmp_path, clock)
    connected_at = clock.now

    assert not service.record_snapshot(analysis(), connected_at)
    clock.now += timedelta(seconds=59)
    assert not service.record_snapshot(analysis(), connected_at)
    clock.now += timedelta(seconds=1)
    assert service.record_snapshot(analysis(), connected_at)
    assert len(service.snapshot_store.history("U1")) == 1


def test_no_snapshot_without_connection_account_or_net_liquidation(tmp_path):
    clock = Clock(ny(2026, 9, 29, 11, 0))
    service = recording_service(tmp_path, clock)

    assert not service.record_snapshot(analysis(connected=False), WARM_VIEWER)
    assert not service.record_snapshot(analysis(None), WARM_VIEWER)
    assert not service.record_snapshot(analysis(net_liquidation=None), WARM_VIEWER)
    # Skipped views do not start the one-minute throttle.
    assert service.record_snapshot(analysis(), WARM_VIEWER)

    without_store = PortfolioAnalysisService(
        FakePortfolioClient(connected=True),
        BlockingBetaService(),
        risk_free_rate=0.04,
    )
    assert not without_store.record_snapshot(analysis(), WARM_VIEWER)


def test_incomplete_analysis_never_replaces_a_snapshot(tmp_path):
    clock = Clock(ny(2026, 9, 29, 11, 0))
    clock.now = ny(2026, 9, 26, 12, 0)
    service = recording_service(tmp_path, clock)
    assert service.record_snapshot(analysis(net_liquidation=100_000), WARM_VIEWER)

    # A weekend view before TWS sends positions, then views missing market data.
    clock.now += timedelta(minutes=1)
    no_positions = analysis(net_liquidation=90_000).model_copy(
        update={
            "underlyings": [],
            "summary": analysis().summary.model_copy(
                update={"coverage": AnalysisCoverage(), "beta_weighted_delta": 0}
            ),
        }
    )
    assert not service.record_snapshot(no_positions, WARM_VIEWER)
    assert not service.record_snapshot(analysis(flags=("missing_price",)), WARM_VIEWER)
    assert not service.record_snapshot(analysis(flags=("missing_greeks",)), WARM_VIEWER)
    # Skipped views do not start the one-minute throttle; fallback data is still complete.
    assert service.record_snapshot(
        analysis(net_liquidation=101_000, flags=("fallback_greeks", "fallback_beta")),
        WARM_VIEWER,
    )

    [row] = service.snapshot_store.history("U1")
    assert (row.session_date, row.kind, row.net_liquidation) == (
        date(2026, 9, 25),
        "post_close",
        101_000,
    )


def test_only_a_connected_viewer_records_history():
    portfolio_client = connected_client()
    api = make_api(portfolio_client)
    clock = Clock(ny(2026, 9, 29, 11, 0))

    with TestClient(api) as client:
        api.state.portfolio_analysis_service.now = clock
        portfolio_client.allow_refresh.set()
        # Wait for the refreshed snapshot so the GET analyses a connected account.
        with client.websocket_connect("/portfolio/ws") as portfolio_ws:
            while not portfolio_ws.receive_json()["status"]["connected"]:
                pass
        clock.now += timedelta(minutes=5)
        analysed = client.get("/portfolio/analysis", params={"account": "DU1234567"}).json()
        before = client.get("/portfolio/analysis/history", params={"account": "DU1234567"})

        with client.websocket_connect("/portfolio/analysis/ws") as websocket:
            first = websocket.receive_json()
            during_warm_up = client.get(
                "/portfolio/analysis/history", params={"account": "DU1234567"}
            ).json()
            clock.now += timedelta(minutes=1)
            # Any message that names an account rebuilds the analysis.
            websocket.send_json({"account": "DU1234567"})
            websocket.receive_json()
        after = client.get("/portfolio/analysis/history", params={"account": "DU1234567"})
        blank = client.get("/portfolio/analysis/history", params={"account": " "})
        missing = client.get("/portfolio/analysis/history")

    assert analysed["summary"]["net_liquidation"] == 125_000
    assert before.status_code == 200
    assert before.json() == {"account": "DU1234567", "snapshots": []}
    assert first["account"] == "DU1234567"
    assert during_warm_up["snapshots"] == []
    [row] = after.json()["snapshots"]
    assert (row["session_date"], row["kind"]) == ("2026-09-29", "intraday")
    assert row["net_liquidation"] == 125_000
    assert row["beta_weighted_delta_multiple"] == pytest.approx(0.16)
    assert (blank.status_code, missing.status_code) == (400, 422)
