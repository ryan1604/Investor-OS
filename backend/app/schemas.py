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
