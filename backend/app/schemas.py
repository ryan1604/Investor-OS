from typing import Literal

from pydantic import BaseModel, Field


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
