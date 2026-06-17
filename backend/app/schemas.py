from collections.abc import Hashable, Iterable
import math
import re
from typing import Annotated, Any, Literal, NotRequired, Self, TypeVar, TypedDict

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator

from app.tickers import require_ticker

DuplicateValue = TypeVar("DuplicateValue", bound=Hashable)


class IbStatus(BaseModel):
    connected: bool
    host: str
    port: int
    client_id: int


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


MONTH_KEY_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
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
    month: str
    portfolio_value: float | None = None
    amount_invested: float | None = None

    @field_validator("month")
    @classmethod
    def valid_month_key(cls, value: str) -> str:
        normalized_value = value.strip()
        if not MONTH_KEY_PATTERN.fullmatch(normalized_value):
            raise ValueError("month must use YYYY-MM format.")
        return normalized_value

    @field_validator("portfolio_value", "amount_invested")
    @classmethod
    def finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("numeric values must be finite.")
        return value

    @model_validator(mode="after")
    def reject_blank_row(self):
        if self.portfolio_value is None and self.amount_invested is None:
            raise ValueError(
                "portfolio_value or amount_invested is required for each row."
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
    portfolio_value: float | None = None
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
    category: Literal["excluded_contracts", "no_matches"]
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
    "filled",
    "cancelled",
    "rejected",
]
OptionRight = Literal["CALL", "PUT"]


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
    editable: bool = True
    filled: float = 0
    remaining: float | None = None
    avg_fill_price: float | None = None
    rejection_message: str | None = None
    submitted_at: str
    updated_at: str
    preview: OrderPreviewResponse


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
