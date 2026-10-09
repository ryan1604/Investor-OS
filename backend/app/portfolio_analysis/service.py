"""Build Portfolio Analysis responses from cached portfolio snapshots."""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from app.ib.portfolio import PortfolioClient
from app.options.store import CompletedDailyBar
from app.portfolio.nav_store import DailyNavStore
from app.portfolio_analysis.beta import BetaService
from app.portfolio_analysis.exposure import build_account_exposure
from app.portfolio_analysis.pairing import is_supported_position
from app.portfolio_analysis.realised import NavPoint, build_realised_stats
from app.sessions import snapshot_session
from app.portfolio_analysis.snapshot_store import RiskSnapshotStore
from app.portfolio_analysis.stress import build_stress_grid
from app.schemas import (
    AnalysisRealisedStats,
    AnalysisRiskSnapshot,
    PortfolioAnalysisResponse,
    PortfolioResponse,
)

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = timedelta(minutes=1)
# Market data arrives after a viewer connects; earlier snapshots would be incomplete.
SNAPSHOT_WARM_UP = timedelta(minutes=1)


class PortfolioAnalysisService:
    """Compute exposure without IB calls; missing betas resolve in the background."""

    def __init__(
        self,
        client: PortfolioClient,
        beta_service: BetaService,
        *,
        risk_free_rate: float,
        snapshot_store: RiskSnapshotStore | None = None,
        nav_store: DailyNavStore | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.beta_service = beta_service
        self.risk_free_rate = risk_free_rate
        self.snapshot_store = snapshot_store
        self.nav_store = nav_store
        self.now = now
        self.beta_lock = threading.Lock()
        self.beta_thread: threading.Thread | None = None
        self.snapshot_lock = threading.Lock()
        self.last_snapshot_at: dict[str, datetime] = {}

    def build(
        self,
        snapshot: PortfolioResponse,
        account: str | None = None,
    ) -> PortfolioAnalysisResponse:
        now = self.now()
        accounts = snapshot_accounts(snapshot)
        selected = account if account in accounts else (accounts[0] if accounts else None)
        if not snapshot.status.connected or selected is None:
            return PortfolioAnalysisResponse(
                status=snapshot.status,
                account=selected,
                accounts=accounts,
                as_of=now,
                message=snapshot.message or "Portfolio data has not loaded yet.",
            )

        symbols = {
            position.symbol
            for position in snapshot.positions
            if position.account == selected and is_supported_position(position)
        }
        betas = self.beta_service.resolve(symbols, compute=False)
        benchmark_bars = self.beta_service.benchmark_bars(compute=False)
        if benchmark_bars is None or any(beta.pending for beta in betas.values()):
            self.resolve_betas_in_background(symbols)

        account_summary = next(
            (summary for summary in snapshot.accounts if summary.account == selected),
            None,
        )
        exposure = build_account_exposure(
            selected,
            snapshot.positions,
            account_summary,
            self.client.get_analysis_market_data(),
            betas,
            now=now,
            risk_free_rate=self.risk_free_rate,
        )
        return PortfolioAnalysisResponse(
            status=snapshot.status,
            account=selected,
            accounts=accounts,
            as_of=now,
            summary=exposure.summary,
            underlyings=exposure.underlyings,
            unsupported=exposure.unsupported,
            stress=build_stress_grid(
                exposure.underlyings,
                exposure.summary.net_liquidation,
                exposure.summary.maintenance_margin,
                now=now,
                risk_free_rate=self.risk_free_rate,
            ),
            realised=self.realised_stats(selected, benchmark_bars),
            message=f"Analysed {exposure.summary.coverage.positions} position(s).",
        )

    def realised_stats(
        self,
        account: str,
        benchmark_bars: list[CompletedDailyBar] | None,
    ) -> AnalysisRealisedStats | None:
        if self.nav_store is None:
            return None
        rows = self.nav_store.history(account).rows
        return build_realised_stats(
            (
                NavPoint(date.fromisoformat(row.report_date), float(row.nav), row.currency)
                for row in rows
            ),
            benchmark_bars,
        )

    def build_for_viewer(
        self,
        snapshot: PortfolioResponse,
        account: str | None,
        viewer_since: datetime,
    ) -> PortfolioAnalysisResponse:
        """Build for a connected viewer; only viewers record risk history."""
        response = self.build(snapshot, account)
        try:
            self.record_snapshot(response, viewer_since)
        except Exception:
            logger.exception("Could not record a Portfolio Analysis risk snapshot")
        return response

    def record_snapshot(
        self,
        response: PortfolioAnalysisResponse,
        viewer_since: datetime,
    ) -> bool:
        """Store at most one snapshot per account per minute, once the viewer has been
        connected for the warm-up and the analysis is complete. Returns whether one was
        written.
        """
        now = self.now()
        if (
            self.snapshot_store is None
            or not response.status.connected
            or response.account is None
            or response.summary.net_liquidation is None
            or now - viewer_since < SNAPSHOT_WARM_UP
            or not is_complete_analysis(response)
        ):
            return False
        with self.snapshot_lock:
            last = self.last_snapshot_at.get(response.account)
            if last is not None and now - last < SNAPSHOT_INTERVAL:
                return False
            self.last_snapshot_at[response.account] = now
        return self.snapshot_store.save(response.account, risk_snapshot(response, now))

    def resolve_betas_in_background(self, symbols: set[str]) -> None:
        """Fetch missing betas and SPY bars off the refresh path; one fetch runs at a time."""
        with self.beta_lock:
            if self.beta_thread is not None and self.beta_thread.is_alive():
                return
            self.beta_thread = threading.Thread(
                target=self._resolve_betas,
                args=(sorted(symbols),),
                name="portfolio-analysis-beta",
                daemon=True,
            )
            self.beta_thread.start()

    def _resolve_betas(self, symbols: list[str]) -> None:
        try:
            self.beta_service.benchmark_bars()
            self.beta_service.resolve(symbols)
        except Exception:
            logger.exception("Could not resolve Portfolio Analysis betas")


def is_complete_analysis(response: PortfolioAnalysisResponse) -> bool:
    """True when positions loaded and every leg has a price and Greeks.

    A view before IB sends positions or market data would otherwise store zero
    risk, and a closed-market view could replace a good `post_close` snapshot.
    """
    coverage = response.summary.coverage
    return (
        coverage.positions > 0
        and coverage.missing_price == 0
        and not any(
            "missing_price" in leg.flags or "missing_greeks" in leg.flags
            for underlying in response.underlyings
            for group in underlying.groups
            for leg in group.legs
        )
    )


def risk_snapshot(response: PortfolioAnalysisResponse, now: datetime) -> AnalysisRiskSnapshot:
    session_date, kind = snapshot_session(now)
    summary = response.summary
    stress = response.stress
    down_20 = (
        next((cell for cell in stress.realistic_path if cell.spy_move_percent == -20), None)
        if stress is not None
        else None
    )
    return AnalysisRiskSnapshot(
        session_date=session_date,
        kind=kind,
        captured_at=now,
        net_liquidation=summary.net_liquidation,
        beta_weighted_delta=summary.beta_weighted_delta,
        beta_weighted_delta_multiple=summary.beta_weighted_delta_multiple,
        net_gamma=summary.net_gamma,
        net_theta=summary.net_theta,
        net_vega=summary.net_vega,
        assignment_exposure=summary.assignment_exposure,
        assignment_exposure_percent=summary.assignment_exposure_percent,
        maintenance_margin=summary.maintenance_margin,
        margin_utilisation_percent=summary.margin_utilisation_percent,
        excess_liquidity=summary.excess_liquidity,
        largest_underlying=summary.largest_underlying,
        largest_underlying_percent=summary.largest_underlying_percent,
        realistic_down_20_pnl=down_20.pnl if down_20 else None,
        realistic_down_20_pnl_percent=down_20.pnl_percent if down_20 else None,
        model_margin=stress.margin.model_margin if stress else None,
        calibration_factor=stress.margin.calibration_factor if stress else None,
        distance_to_margin_call_percent=(
            stress.margin.distance_to_margin_call_percent if stress else None
        ),
        margin_call_beyond_path=stress.margin.margin_call_beyond_path if stress else False,
    )


def snapshot_accounts(snapshot: PortfolioResponse) -> list[str]:
    # Sorted like the frontend's account selector.
    return sorted(
        {summary.account for summary in snapshot.accounts}
        | {position.account for position in snapshot.positions}
    )
