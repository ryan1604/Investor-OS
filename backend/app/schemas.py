from collections.abc import Hashable, Iterable
from datetime import date, datetime
import math
import re
from typing import Annotated, Any, Literal, NotRequired, Self, TypeVar, TypedDict
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    computed_field,
    field_validator,
    model_validator,
)

from app.tickers import require_ticker

DuplicateValue = TypeVar("DuplicateValue", bound=Hashable)


class IbStatus(BaseModel):
    connected: bool
    host: str
    port: int
    client_id: int


class MarketDataLineUsage(BaseModel):
    """Read-only view of the shared IB market-data line budget."""

    capacity: int
    used: int
    used_by_group: dict[str, int]
    pending_by_group: dict[str, int]


class PortfolioPosition(BaseModel):
    account: str
    con_id: int | None = None
    symbol: str
    sec_type: str
    local_symbol: str | None = None
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    multiplier: str | None = None
    exchange: str
    currency: str
    quantity: float
    average_cost: float | None = None
    last_price: float | None = None
    change_percent: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_percent: float | None = None
    market_value: float | None = None
    cost_basis: float | None = None
    average_price: float | None = None
    net_liquidity: float | None = None
    net_liquidity_percent: float | None = None


class PortfolioAccountSummary(BaseModel):
    account: str
    currency: str = "USD"
    net_liquidation: float | None = None
    daily_pnl: float | None = None
    daily_pnl_percent: float | None = None
    unrealized_pnl: float | None = None
    market_value: float | None = None
    maintenance_margin: float | None = None
    excess_liquidity: float | None = None
    buying_power: float | None = None
    cash_total_sgd: float | None = None
    cash_total_usd: float | None = None
    cash_total: float | None = None


class PortfolioResponse(BaseModel):
    status: IbStatus
    accounts: list[PortfolioAccountSummary] = Field(default_factory=list)
    positions: list[PortfolioPosition]
    message: str | None = None


MAX_BETA_OVERRIDE = 10


class BetaOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beta: float

    @field_validator("beta")
    @classmethod
    def bounded_finite_beta(cls, value: float) -> float:
        if not math.isfinite(value) or abs(value) > MAX_BETA_OVERRIDE:
            raise ValueError(f"beta must be a finite number between -{MAX_BETA_OVERRIDE} and {MAX_BETA_OVERRIDE}.")
        return value


class BetaOverrideResponse(BaseModel):
    ticker: str
    beta: float
    updated_at: str


# Upper bounds: beta-weighted delta (x NLV), margin use, assignment, largest underlying (%).
# Lower bounds, stored as positive numbers: realistic-path -20% loss (P&L >= -value %)
# and distance to margin call (SPY drop >= value %).
RiskLimitKey = Literal[
    "beta_weighted_delta_multiple",
    "margin_utilisation_percent",
    "assignment_exposure_percent",
    "largest_underlying_percent",
    "realistic_path_loss_percent",
    "margin_call_distance_percent",
]


class RiskLimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limits: dict[RiskLimitKey, float]

    @field_validator("limits")
    @classmethod
    def finite_non_negative_limits(cls, limits: dict[str, float]) -> dict[str, float]:
        for key, value in limits.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a finite number of at least 0.")
        return limits


class RiskLimitResponse(BaseModel):
    key: RiskLimitKey
    value: float
    updated_at: str


class RiskLimitsResponse(BaseModel):
    account: str
    limits: list[RiskLimitResponse] = Field(default_factory=list)


AnalysisGreeksSource = Literal["ib", "fallback", "solved_iv", "missing"]
AnalysisBetaSource = Literal["override", "computed", "fallback"]


class AnalysisExposure(BaseModel):
    """USD exposure; gamma is the change in dollar delta for a 1% underlying move."""

    dollar_delta: float = 0
    beta_weighted_delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0


class AnalysisLeg(AnalysisExposure):
    con_id: int | None = None
    symbol: str
    sec_type: str
    local_symbol: str | None = None
    right: str | None = None
    strike: float | None = None
    expiry: str | None = None
    currency: str
    # Signed shares or contracts assigned to the group.
    quantity: float
    price: float | None = None
    underlying_price: float | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    greeks_source: AnalysisGreeksSource | None = None
    fx_rate: float = 1
    flags: list[str] = Field(default_factory=list)


class AnalysisGroup(AnalysisExposure):
    kind: str
    label: str
    quantity: float
    premium_type: Literal["credit", "debit"] | None = None
    net_premium: float | None = None
    # None means unlimited.
    max_loss: float | None = None
    assignment_exposure: float = 0
    legs: list[AnalysisLeg] = Field(default_factory=list)


class AnalysisUnderlying(AnalysisExposure):
    symbol: str
    beta: float
    beta_source: AnalysisBetaSource
    beta_observations: int | None = None
    underlying_price: float | None = None
    net_liquidation_percent: float | None = None
    max_loss: float | None = None
    max_loss_unlimited: bool = False
    assignment_exposure: float = 0
    groups: list[AnalysisGroup] = Field(default_factory=list)


class AnalysisUnsupportedPosition(BaseModel):
    con_id: int | None = None
    symbol: str
    sec_type: str
    local_symbol: str | None = None
    currency: str
    quantity: float
    reason: str


class AnalysisCoverage(BaseModel):
    positions: int = 0
    fallback_greeks: int = 0
    fallback_beta: int = 0
    unsupported: int = 0
    fx_converted: int = 0
    missing_price: int = 0


class AnalysisSummary(BaseModel):
    net_liquidation: float | None = None
    gross_dollar_delta: float = 0
    net_dollar_delta: float = 0
    beta_weighted_delta: float = 0
    beta_weighted_delta_multiple: float | None = None
    net_gamma: float = 0
    net_theta: float = 0
    net_vega: float = 0
    assignment_exposure: float = 0
    assignment_exposure_percent: float | None = None
    maintenance_margin: float | None = None
    margin_utilisation_percent: float | None = None
    excess_liquidity: float | None = None
    largest_underlying: str | None = None
    largest_underlying_percent: float | None = None
    coverage: AnalysisCoverage = Field(default_factory=AnalysisCoverage)


class AnalysisStressCell(BaseModel):
    spy_move_percent: float
    iv_shock_percent: float
    pnl: float
    pnl_percent: float | None = None
    # Stressed net liquidation minus calibrated model margin; None without net liquidation.
    excess_liquidity: float | None = None
    realistic_path: bool = False


class AnalysisMarginEstimate(BaseModel):
    """Reg T model margin at no shock, scaled up to IB's figure by the calibration factor."""

    model_margin: float = 0
    ib_maintenance_margin: float | None = None
    calibration_factor: float = 1
    # Groups with a leg that could not be priced add no model margin.
    excluded_groups: int = 0
    # SPY drop along the realistic path at which excess liquidity reaches zero.
    distance_to_margin_call_percent: float | None = None
    margin_call_beyond_path: bool = False


class AnalysisStressGrid(BaseModel):
    """Estimated P&L per SPY move x relative IV shock; cells run SPY move first."""

    spy_moves_percent: list[float] = Field(default_factory=list)
    iv_shocks_percent: list[float] = Field(default_factory=list)
    cells: list[AnalysisStressCell] = Field(default_factory=list)
    realistic_path: list[AnalysisStressCell] = Field(default_factory=list)
    legs: int = 0
    excluded_legs: int = 0
    margin: AnalysisMarginEstimate = Field(default_factory=AnalysisMarginEstimate)


class AnalysisRealisedValue(BaseModel):
    """A realised statistic; value is None with a reason when history is too short."""

    value: float | None = None
    observations: int = 0
    reason: str | None = None


class AnalysisRealisedStats(BaseModel):
    """Statistics from the daily NAV history (Flex), which includes deposits and withdrawals."""

    currency: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    nav_observations: int = 0
    volatility_20d_percent: AnalysisRealisedValue
    volatility_60d_percent: AnalysisRealisedValue
    # Drawdowns are negative percents from the running peak.
    max_drawdown_percent: AnalysisRealisedValue
    current_drawdown_percent: AnalysisRealisedValue
    beta: AnalysisRealisedValue


class PortfolioAnalysisResponse(BaseModel):
    status: IbStatus
    account: str | None = None
    accounts: list[str] = Field(default_factory=list)
    as_of: datetime
    summary: AnalysisSummary = Field(default_factory=AnalysisSummary)
    underlyings: list[AnalysisUnderlying] = Field(default_factory=list)
    unsupported: list[AnalysisUnsupportedPosition] = Field(default_factory=list)
    stress: AnalysisStressGrid | None = None
    realised: AnalysisRealisedStats | None = None
    message: str | None = None


RiskSnapshotKind = Literal["post_close", "intraday"]


class AnalysisRiskSnapshot(BaseModel):
    """Account-level risk metrics captured for one US trading session."""

    session_date: date
    kind: RiskSnapshotKind
    captured_at: datetime
    net_liquidation: float | None = None
    beta_weighted_delta: float = 0
    beta_weighted_delta_multiple: float | None = None
    net_gamma: float = 0
    net_theta: float = 0
    net_vega: float = 0
    assignment_exposure: float = 0
    assignment_exposure_percent: float | None = None
    maintenance_margin: float | None = None
    margin_utilisation_percent: float | None = None
    excess_liquidity: float | None = None
    largest_underlying: str | None = None
    largest_underlying_percent: float | None = None
    realistic_down_20_pnl: float | None = None
    realistic_down_20_pnl_percent: float | None = None
    model_margin: float | None = None
    calibration_factor: float | None = None
    distance_to_margin_call_percent: float | None = None
    margin_call_beyond_path: bool = False


class PortfolioAnalysisHistoryResponse(BaseModel):
    account: str
    snapshots: list[AnalysisRiskSnapshot] = Field(default_factory=list)


MONTH_KEY_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DAY_TRADING_MIN_DATE = "2026-08-01"
OPTIONS_TRADE_MONTHS = {
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
}


class PortfolioChartValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str
    amount_invested: float | None = None

    @field_validator("month")
    @classmethod
    def valid_month_key(cls, value: str) -> str:
        normalized_value = value.strip()
        if not MONTH_KEY_PATTERN.fullmatch(normalized_value):
            raise ValueError("month must use YYYY-MM format.")
        return normalized_value

    @field_validator("amount_invested")
    @classmethod
    def finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("numeric values must be finite.")
        return value

    @model_validator(mode="after")
    def reject_blank_row(self):
        if self.amount_invested is None:
            raise ValueError(
                "amount_invested is required for each row."
            )
        return self


class PortfolioChartValuesRequest(BaseModel):
    rows: list[PortfolioChartValueRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_months(self):
        months = [row.month for row in self.rows]
        duplicate_months = duplicate_values(months)
        if duplicate_months:
            raise ValueError(
                f"Duplicate month values are not allowed: {', '.join(duplicate_months)}."
            )
        return self


class PortfolioChartValueResponse(BaseModel):
    month: str
    amount_invested: float | None = None
    updated_at: str


class PortfolioChartValuesResponse(BaseModel):
    account: str
    rows: list[PortfolioChartValueResponse] = Field(default_factory=list)


OptionsTradeStatus = Literal["In Progress", "Completed"]


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized_value = value.strip()
    return normalized_value or None


def normalize_optional_upper_text(value: str | None) -> str | None:
    normalized_value = normalize_optional_text(value)
    return normalized_value.upper() if normalized_value is not None else None


def normalize_strategy_option(value: str) -> str:
    normalized_value = " ".join(value.strip().split())
    if not normalized_value:
        return ""

    return normalized_value.upper()


def duplicate_values(
    values: Iterable[DuplicateValue],
) -> list[DuplicateValue]:
    seen: set[DuplicateValue] = set()
    duplicates: set[DuplicateValue] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return sorted(duplicates)


class DayTradingRowRequest(BaseModel):
    id: str | None = None
    display_order: int = Field(ge=0)
    buy: float | None = None
    sell: float | None = None
    size: StrictInt | None = None
    fee: float | None = None

    @field_validator("id", mode="before")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("buy", "sell", "fee")
    @classmethod
    def finite_price(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("numeric values must be finite.")
        return value

    @field_validator("fee")
    @classmethod
    def non_negative_fee(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("fee must be zero or greater.")
        return value

    @field_validator("size")
    @classmethod
    def positive_size(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("size must be a positive whole number.")
        return value


class DayTradingRowsReplaceRequest(BaseModel):
    trades: list[DayTradingRowRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_row_ordering(self) -> Self:
        row_ids = [row.id for row in self.trades if row.id is not None]
        duplicate_row_ids = duplicate_values(row_ids)
        if duplicate_row_ids:
            raise ValueError("Duplicate trade row ids are not allowed.")

        display_orders = [row.display_order for row in self.trades]
        duplicate_orders = duplicate_values(display_orders)
        if duplicate_orders:
            raise ValueError("Duplicate trade row display_order values are not allowed.")

        return self


class DayTradingRowResponse(BaseModel):
    id: str
    display_order: int
    buy: float | None = None
    sell: float | None = None
    size: int | None = None
    fee: float | None = None
    created_at: str
    updated_at: str


class DayTradingDayResponse(BaseModel):
    date: str
    trades: list[DayTradingRowResponse] = Field(default_factory=list)


class DayTradingMonthResponse(BaseModel):
    month: str
    days: list[DayTradingDayResponse] = Field(default_factory=list)


class OptionsTradeTrackerCreateRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def non_empty_name(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Tracker name is required.")
        return normalized_value


class OptionsTradeTrackerRenameRequest(OptionsTradeTrackerCreateRequest):
    pass


class OptionsTradeTrackerSummaryResponse(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str


class OptionsTradeTrackerListResponse(BaseModel):
    trackers: list[OptionsTradeTrackerSummaryResponse] = Field(default_factory=list)


class OptionsTradeRowRequest(BaseModel):
    id: str | None = None
    display_order: int = Field(ge=0)
    status: OptionsTradeStatus = "In Progress"
    strategy: str | None = None
    ticker: str | None = None
    month: str | None = None
    expiry_date: date | None = None
    size: float | None = None
    strike_price: float | None = None
    credit_debit: float | None = None
    exit: float | None = None

    @field_validator("id", mode="before")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("strategy", mode="before")
    @classmethod
    def optional_strategy(cls, value: str | None) -> str | None:
        normalized_value = normalize_optional_text(value)
        return (
            normalize_strategy_option(normalized_value)
            if normalized_value is not None
            else None
        )

    @field_validator("ticker", mode="before")
    @classmethod
    def optional_ticker(cls, value: str | None) -> str | None:
        return normalize_optional_upper_text(value)

    @field_validator("month", mode="before")
    @classmethod
    def optional_month(cls, value: str | None) -> str | None:
        normalized_value = normalize_optional_text(value)
        if normalized_value is not None:
            tracker_month = normalized_value.lower()
            if tracker_month not in OPTIONS_TRADE_MONTHS:
                raise ValueError("month must be jan-dec.")
            return tracker_month
        return normalized_value

    @field_validator("size", "strike_price", "credit_debit", "exit")
    @classmethod
    def finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("numeric values must be finite.")
        return value

    @model_validator(mode="after")
    def validate_completed_row(self) -> Self:
        if self.strike_price is not None and self.strike_price <= 0:
            raise ValueError("strike_price must be greater than zero.")
        if self.credit_debit is not None and self.credit_debit <= 0:
            raise ValueError("credit_debit must be greater than zero.")
        if self.exit is not None and self.exit < 0:
            raise ValueError("exit must be greater than or equal to zero.")

        if self.status != "Completed":
            return self

        missing_fields = [
            field_name
            for field_name in (
                "strategy",
                "ticker",
                "month",
                "size",
                "strike_price",
                "credit_debit",
            )
            if getattr(self, field_name) is None
        ]
        if missing_fields:
            raise ValueError(
                "Completed rows require strategy, ticker, month, size, "
                "strike_price, and credit_debit."
            )

        if self.size == 0:
            raise ValueError("Completed rows require non-zero size.")
        return self


class OptionsTradeRowsReplaceRequest(BaseModel):
    trades: list[OptionsTradeRowRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_row_ordering(self) -> Self:
        row_ids = [row.id for row in self.trades if row.id is not None]
        duplicate_row_ids = duplicate_values(row_ids)
        if duplicate_row_ids:
            raise ValueError("Duplicate trade row ids are not allowed.")

        display_orders = [row.display_order for row in self.trades]
        duplicate_orders = duplicate_values(display_orders)
        if duplicate_orders:
            raise ValueError("Duplicate trade row display_order values are not allowed.")

        return self


class OptionsTradeNotesRequest(BaseModel):
    notes: str = ""


class OptionsTradeStrategiesRequest(BaseModel):
    strategies: list[str] = Field(default_factory=list)

    @field_validator("strategies")
    @classmethod
    def normalize_strategies(cls, values: list[str]) -> list[str]:
        normalized_values = [normalize_strategy_option(value) for value in values]
        blank_values = [value for value in normalized_values if not value]
        if blank_values:
            raise ValueError("Strategy options cannot be blank.")

        normalized_lookup_values = [value.lower() for value in normalized_values]
        duplicate_strategy_values = duplicate_values(normalized_lookup_values)
        if duplicate_strategy_values:
            raise ValueError("Duplicate strategy options are not allowed.")

        return normalized_values


class OptionsTradeStrategyOptionsResponse(BaseModel):
    strategies: list[str] = Field(default_factory=list)


class OptionsTradeRowResponse(BaseModel):
    id: str
    display_order: int
    status: OptionsTradeStatus
    strategy: str | None = None
    ticker: str | None = None
    month: str | None = None
    expiry_date: str | None = None
    size: float | None = None
    strike_price: float | None = None
    credit_debit: float | None = None
    exit: float | None = None
    created_at: str
    updated_at: str


class OptionsTradeTrackerDetailResponse(BaseModel):
    tracker: OptionsTradeTrackerSummaryResponse
    trades: list[OptionsTradeRowResponse] = Field(default_factory=list)
    notes: str = ""
    strategy_options: list[str] = Field(default_factory=list)


class OptionDailyBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class BollingerBandPoint(BaseModel):
    date: str
    upper: float | None = None
    middle: float | None = None
    lower: float | None = None


class RsiPoint(BaseModel):
    date: str
    value: float | None = None


class OptionExpiration(BaseModel):
    date: str
    days_to_expiration: int | None = None


class OptionQuote(BaseModel):
    local_symbol: str | None = None
    delta: float | None = None
    bid: float | None = None
    bid_size: int | None = None
    ask: float | None = None
    ask_size: int | None = None
    mid: float | None = None
    last: float | None = None
    close: float | None = None
    model_price: float | None = None
    change_percent: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    gamma: float | None = None
    theta: float | None = None
    implied_volatility_percent: float | None = None
    breakeven: float | None = None


class OptionChainRow(BaseModel):
    strike: float
    call: OptionQuote | None = None
    put: OptionQuote | None = None


class OptionsAnalysisResponse(BaseModel):
    ticker: str
    underlying_price: float | None = None
    candles: list[OptionDailyBar] = Field(default_factory=list)
    bollinger_bands: list[BollingerBandPoint] = Field(default_factory=list)
    rsi: list[RsiPoint] = Field(default_factory=list)
    message: str | None = None


class OptionExpirationsResponse(BaseModel):
    ticker: str
    expirations: list[OptionExpiration] = Field(default_factory=list)
    selected_expiration: str | None = None
    message: str | None = None


class OptionChainResponse(BaseModel):
    ticker: str
    expiration: str
    underlying_price: float | None = None
    rows: list[OptionChainRow] = Field(default_factory=list)
    message: str | None = None


class OptionChainLiveMessage(BaseModel):
    type: Literal["snapshot", "update"]
    ticker: str
    expiration: str
    rows: list[OptionChainRow] | None = None
    row: OptionChainRow | None = None
    message: str | None = None
    warning: str | None = None


class OptionsChartLiveMessage(BaseModel):
    type: Literal["update"]
    ticker: str
    candle: OptionDailyBar
    bollinger_band: BollingerBandPoint
    rsi: RsiPoint


class StockAnalysisPayload(TypedDict):
    bull: dict[str, Any]
    base: dict[str, Any]
    bear: dict[str, Any]
    firstForecastYear: NotRequired[int | None]


def empty_stock_analysis_payload() -> StockAnalysisPayload:
    return {"bull": {}, "base": {}, "bear": {}}


class StockAnalysisModelRequest(BaseModel):
    version: int = 1
    payload: StockAnalysisPayload = Field(default_factory=empty_stock_analysis_payload)

    @model_validator(mode="after")
    def validate_payload_shape(self):
        for scenario in ("bull", "base", "bear"):
            if scenario not in self.payload:
                raise ValueError(f"payload.{scenario} is required.")
        return self


class StockAnalysisModelResponse(BaseModel):
    ticker: str
    version: int = 1
    current_price: float | None = None
    payload: StockAnalysisPayload = Field(default_factory=empty_stock_analysis_payload)
    updated_at: str | None = None


class StockAnalysisCurrentPriceResponse(BaseModel):
    ticker: str
    current_price: float


class StockAnalysisPriceRefreshResult(BaseModel):
    ticker: str
    status: Literal["refreshed", "stale", "missing", "failed"]
    current_price: float | None = None
    message: str | None = None


class StockAnalysisPriceRefreshResponse(BaseModel):
    results: list[StockAnalysisPriceRefreshResult] = Field(default_factory=list)


EarningsWatchRowStatus = Literal["upcoming", "last_known", "no_date"]
EarningsWatchRefreshStatus = Literal[
    "never_attempted",
    "refreshing",
    "succeeded",
    "failed",
    "cooldown",
]


class EarningsWatchRowResponse(BaseModel):
    ticker: str
    reviewed: bool
    earnings_date: str | None = None
    status: EarningsWatchRowStatus
    created_at: str
    updated_at: str


class EarningsWatchRefreshState(BaseModel):
    state: EarningsWatchRefreshStatus
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_success_date: str | None = None
    error_category: str | None = None
    next_eligible_retry_at: str | None = None


class EarningsWatchResponse(BaseModel):
    rows: list[EarningsWatchRowResponse] = Field(default_factory=list)
    refresh: EarningsWatchRefreshState


class EarningsWatchStateResponse(BaseModel):
    rows: list[EarningsWatchRowResponse] = Field(default_factory=list)


class EarningsWatchAddTickersRequest(BaseModel):
    tickers: str


class EarningsWatchAddTickersResponse(EarningsWatchStateResponse):
    added: list[str] = Field(default_factory=list)
    existing: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)


class EarningsWatchReviewedRequest(BaseModel):
    reviewed: bool


OptionsScreenerTickerList = Literal["csp_cc", "cs"]
OptionsScreener = Literal["csp", "cc", "cs"]
CreditSpreadStrategy = Literal["put_credit_spread", "call_credit_spread"]
CreditSpreadWidth = Literal[1.0, 2.0, 2.5, 5.0, 10.0]


class OptionsScreenerFilters(BaseModel):
    version: int = Field(default=1, ge=1)
    minimum_dte: int = 7
    maximum_dte: int = 45
    minimum_absolute_delta: float = 0.15
    maximum_absolute_delta: float = 0.30
    minimum_annualized_return: float = 10

    @model_validator(mode="after")
    def validate_ranges(self):
        if not 1 <= self.minimum_dte <= self.maximum_dte:
            raise ValueError(
                "DTE range must satisfy 1 <= minimum_dte <= maximum_dte."
            )
        if not (
            0
            <= self.minimum_absolute_delta
            <= self.maximum_absolute_delta
            <= 1
        ):
            raise ValueError(
                "Absolute delta range must satisfy "
                "0 <= minimum_absolute_delta <= maximum_absolute_delta <= 1."
            )
        if (
            not math.isfinite(self.minimum_annualized_return)
            or self.minimum_annualized_return < 0
        ):
            raise ValueError("minimum_annualized_return must be finite and >= 0.")
        return self


class CreditSpreadScreenerFilters(OptionsScreenerFilters):
    strategy_types: list[CreditSpreadStrategy] = Field(
        default_factory=lambda: [
            "put_credit_spread",
            "call_credit_spread",
        ]
    )
    spread_widths: list[CreditSpreadWidth] = Field(default_factory=lambda: [5.0])

    @field_validator("strategy_types", "spread_widths")
    @classmethod
    def require_unique_selection(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("At least one value is required.")
        if len(value) != len(set(value)):
            raise ValueError("Duplicate values are not allowed.")
        return value


class OptionsScreenerTickerListRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)


class OptionsScreenerTickerListResponse(BaseModel):
    list_name: OptionsScreenerTickerList
    tickers: list[str] = Field(default_factory=list)


class OptionsScreenerFilterSettings(BaseModel):
    csp: OptionsScreenerFilters
    cc: OptionsScreenerFilters
    cs: CreditSpreadScreenerFilters


class OptionsScreenerSettingsResponse(BaseModel):
    ticker_lists: dict[OptionsScreenerTickerList, list[str]]
    filters: OptionsScreenerFilterSettings


class OptionContractIdentity(BaseModel):
    con_id: int | None = None
    local_symbol: str | None = None


class CashSecuredPutCandidate(BaseModel):
    strategy: Literal["csp"] = "csp"
    ticker: str
    annualized_return: float
    stock_price: float
    strike: float
    expiration: str
    dte: int
    delta: float
    bid: float
    ask: float
    discount_percentage: float
    contract: OptionContractIdentity


class CoveredCallCandidate(BaseModel):
    strategy: Literal["cc"] = "cc"
    ticker: str
    annualized_return: float
    stock_price: float
    strike: float
    expiration: str
    dte: int
    delta: float
    bid: float
    ask: float
    gain_percentage: float
    contract: OptionContractIdentity


class CreditSpreadCandidate(BaseModel):
    strategy: CreditSpreadStrategy
    ticker: str
    annualized_return: float
    stock_price: float
    short_strike: float
    long_strike: float
    expiration: str
    dte: int
    short_delta: float
    net_bid: float
    net_ask: float
    distance_percentage: float
    short_contract: OptionContractIdentity
    long_contract: OptionContractIdentity


ScreenerCandidate = Annotated[
    CashSecuredPutCandidate | CoveredCallCandidate | CreditSpreadCandidate,
    Field(discriminator="strategy"),
]
OptionsScreenerJobStatus = Literal[
    "active",
    "completed",
    "cancelled",
    "failed",
]


class OptionsScreenerTickerWarning(BaseModel):
    ticker: str
    category: Literal["excluded_contracts", "no_matches", "line_limit"]
    message: str
    count: int = Field(default=0, ge=0)


class OptionsScreenerScanJob(BaseModel):
    id: str
    screener: OptionsScreener
    status: OptionsScreenerJobStatus
    tickers: list[str]
    filters: OptionsScreenerFilters | CreditSpreadScreenerFilters
    total_tickers: int
    completed_tickers: int = 0
    progress_message: str
    successful_tickers: int = 0
    no_match_tickers: int = 0
    failed_tickers: int = 0
    total_match_count: int = 0
    excluded_contracts: int = 0
    candidates: list[ScreenerCandidate] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[OptionsScreenerTickerWarning] = Field(default_factory=list)
    started_at: str
    finished_at: str | None = None
    successful_completion_at: str | None = None


class OptionsScreenerCompletedSnapshot(BaseModel):
    screener: OptionsScreener
    job_id: str
    total_match_count: int = 0
    excluded_contracts: int = 0
    candidates: list[ScreenerCandidate] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[OptionsScreenerTickerWarning] = Field(default_factory=list)
    completed_at: str


class OptionsScreenerScanState(BaseModel):
    active_job: OptionsScreenerScanJob | None = None
    latest_jobs: dict[OptionsScreener, OptionsScreenerScanJob | None]
    completed_snapshots: dict[
        OptionsScreener,
        OptionsScreenerCompletedSnapshot | None,
    ]


class OptionsScreenerScanEvent(BaseModel):
    type: Literal["job_started", "job_updated", "job_finished"]
    job: OptionsScreenerScanJob


class OptionsScreenerQuoteRefreshRequest(BaseModel):
    ticker: str
    expiration: str
    strike: float
    right: Literal["CALL", "PUT"]
    contract: OptionContractIdentity


class OptionsScreenerQuoteRefreshResponse(BaseModel):
    ticker: str
    expiration: str
    strike: float
    right: Literal["CALL", "PUT"]
    contract: OptionContractIdentity
    bid: float
    ask: float
    midpoint: float
    delta: float | None = None
    refreshed_at: str


class OptionsScreenerSpreadQuoteRefreshRequest(BaseModel):
    strategy: CreditSpreadStrategy
    ticker: str
    expiration: str
    short_strike: float
    long_strike: float
    short_contract: OptionContractIdentity
    long_contract: OptionContractIdentity


class OptionsScreenerSpreadQuoteRefreshResponse(BaseModel):
    strategy: CreditSpreadStrategy
    ticker: str
    expiration: str
    right: Literal["CALL", "PUT"]
    short_strike: float
    long_strike: float
    short_contract: OptionContractIdentity
    long_contract: OptionContractIdentity
    short_bid: float
    short_ask: float
    short_midpoint: float
    long_bid: float
    long_ask: float
    long_midpoint: float
    short_delta: float | None = None
    net_bid: float
    net_ask: float
    net_midpoint: float
    maximum_loss: float
    refreshed_at: str


OrderAction = Literal["BUY", "SELL"]
OrderTimeInForce = Literal["DAY", "GTC"]
OrderType = Literal["MARKET", "LIMIT"]
OrderStatus = Literal[
    "submitted",
    "working",
    "partially_filled",
    "stale",
    "filled",
    "cancelled",
    "rejected",
]
OrderReconciliationStatus = Literal["pending", "confirmed", "stale"]
OptionRight = Literal["CALL", "PUT"]
OPEN_ORDER_STATUSES = {"submitted", "working", "partially_filled"}
TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected"}
ORDER_SECTION_TIME_ZONE = ZoneInfo("America/New_York")


def normalize_required_text(value: str, message: str) -> str:
    normalized_value = value.strip().upper()
    if not normalized_value:
        raise ValueError(message)
    return normalized_value


def normalize_required_ticker(value: str) -> str:
    try:
        return require_ticker(value)
    except ValueError as error:
        raise ValueError("Ticker is required.") from error


def normalize_required_account(value: str) -> str:
    return normalize_required_text(value, "Account is required.")


def parse_order_section_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ORDER_SECTION_TIME_ZONE)
    return parsed.astimezone(ORDER_SECTION_TIME_ZONE)


class StockOrderRequest(BaseModel):
    order_kind: Literal["stock"] = "stock"
    account: str
    ticker: str
    action: OrderAction
    quantity: StrictInt
    order_type: OrderType = "MARKET"
    limit_price: float | None = None
    time_in_force: OrderTimeInForce = "DAY"

    @field_validator("account", "ticker")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        return normalize_required_text(value, "Value is required.")

    @field_validator("quantity", mode="before")
    @classmethod
    def whole_share_quantity(cls, value):
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("quantity must be a whole share count.")
        if isinstance(value, str):
            normalized_value = value.strip()
            if not normalized_value.isdigit():
                raise ValueError("quantity must be a whole share count.")
        return value

    @model_validator(mode="after")
    def validate_quantity_and_price(self):
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero.")
        if self.order_type == "LIMIT" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders.")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be greater than zero.")
        return self


class OptionStrategyLegRequest(BaseModel):
    con_id: int | None = None
    ticker: str
    expiration: str
    right: OptionRight
    strike: float
    action: OrderAction
    quantity: int

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return normalize_required_ticker(value)

    @field_validator("expiration")
    @classmethod
    def non_empty_expiration(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Expiration is required.")
        return normalized_value

    @model_validator(mode="after")
    def validate_leg_values(self):
        if self.strike <= 0:
            raise ValueError("strike must be greater than zero.")
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero.")
        return self


class OptionStrategyOrderRequest(BaseModel):
    order_kind: Literal["option_strategy"] = "option_strategy"
    account: str
    legs: list[OptionStrategyLegRequest] = Field(min_length=1)
    strategy_quantity: StrictInt = 1
    limit_price: float
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    time_in_force: OrderTimeInForce = "DAY"

    @field_validator("account")
    @classmethod
    def non_empty_account(cls, value: str) -> str:
        return normalize_required_account(value)

    @model_validator(mode="after")
    def validate_exit_prices(self):
        if self.strategy_quantity <= 0:
            raise ValueError("strategy_quantity must be greater than zero.")
        if self.take_profit_price is not None and self.take_profit_price <= 0:
            raise ValueError("take_profit_price must be greater than zero.")
        if self.stop_loss_price is not None and self.stop_loss_price <= 0:
            raise ValueError("stop_loss_price must be greater than zero.")
        return self


OrderPreviewableRequest = Annotated[
    StockOrderRequest | OptionStrategyOrderRequest,
    Field(discriminator="order_kind"),
]


class OrderPreviewResponse(BaseModel):
    preview_id: str
    account: str
    order_kind: Literal["stock", "option_strategy"]
    summary: str
    time_in_force: OrderTimeInForce
    estimated_order_type: str
    request: StockOrderRequest | OptionStrategyOrderRequest


class OrderRecord(BaseModel):
    order_id: int
    perm_id: int | None = None
    parent_order_id: int | None = None
    account: str
    status: OrderStatus
    reconciliation_status: OrderReconciliationStatus = "confirmed"
    editable: bool = True
    read_only_reason: str | None = None
    filled: float = 0
    remaining: float | None = None
    avg_fill_price: float | None = None
    rejection_message: str | None = None
    execution_id: str | None = None
    execution_ids: list[str] = Field(default_factory=list)
    execution_time: str | None = None
    execution_side: str | None = None
    execution_quantity: float | None = None
    execution_price: float | None = None
    execution_cumulative_quantity: float | None = None
    completed_time: str | None = None
    completed_status: str | None = None
    terminal_at: str | None = None
    submitted_at: str
    updated_at: str
    preview: OrderPreviewResponse

    @computed_field
    @property
    def display_details(self) -> list[str]:
        details = []
        if self.perm_id is not None:
            details.append(f"Perm ID {self.perm_id}")
        execution_id = self.execution_id or next(iter(self.execution_ids), None)
        if execution_id:
            details.append(f"Execution {execution_id}")
        details.append(f"API order {self.order_id}")
        return details

    @computed_field
    @property
    def is_open(self) -> bool:
        return (
            self.status in OPEN_ORDER_STATUSES
            and self.reconciliation_status != "stale"
        )

    @computed_field
    @property
    def is_current_day_history(self) -> bool:
        if self.status not in TERMINAL_ORDER_STATUSES:
            return False
        timestamp = self.execution_time or self.completed_time or self.terminal_at
        parsed = parse_order_section_time(timestamp)
        if parsed is None:
            return False
        today = datetime.now(ORDER_SECTION_TIME_ZONE).date()
        if parsed.date() == today:
            return True
        stored = parse_order_section_time_without_conversion(timestamp)
        return stored is not None and stored.date() == today


def parse_order_section_time_without_conversion(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


class OrderSubmissionResponse(BaseModel):
    order: OrderRecord
    message: str


class OrderCancellationRequest(BaseModel):
    account: str

    @field_validator("account")
    @classmethod
    def non_empty_account(cls, value: str) -> str:
        return normalize_required_account(value)


class OrderAmendmentRequest(BaseModel):
    account: str
    quantity: StrictInt | None = None
    limit_price: float | None = None
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    time_in_force: OrderTimeInForce | None = None

    @field_validator("account")
    @classmethod
    def non_empty_account(cls, value: str) -> str:
        return normalize_required_account(value)

    @model_validator(mode="after")
    def validate_amendment_values(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be greater than zero.")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be greater than zero.")
        if self.take_profit_price is not None and self.take_profit_price <= 0:
            raise ValueError("take_profit_price must be greater than zero.")
        if self.stop_loss_price is not None and self.stop_loss_price <= 0:
            raise ValueError("stop_loss_price must be greater than zero.")
        return self


class OrderStatusUpdate(BaseModel):
    type: Literal["snapshot", "update"]
    orders: list[OrderRecord] | None = None
    order: OrderRecord | None = None
