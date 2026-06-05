from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class BollingerBandValue:
    date: str
    upper: float | None = None
    middle: float | None = None
    lower: float | None = None


@dataclass(frozen=True)
class RsiValue:
    date: str
    value: float | None = None


@dataclass(frozen=True)
class DailyClose:
    trading_date: str
    close: float


@dataclass(frozen=True)
class RsiState:
    previous_close: float | None
    average_gain: float | None
    average_loss: float | None
    observation_count: int
    period: int


def calculate_bollinger_bands(
    bars: Sequence[DailyClose],
    *,
    period: int = 20,
    standard_deviations: float = 2,
) -> list[BollingerBandValue]:
    if period <= 0:
        raise ValueError("Bollinger period must be greater than zero.")

    values: list[BollingerBandValue] = []

    for index, bar in enumerate(bars):
        if index + 1 < period:
            values.append(BollingerBandValue(date=bar.trading_date))
            continue

        closes = [item.close for item in bars[index + 1 - period : index + 1]]
        middle = sum(closes) / period
        variance = sum((close - middle) ** 2 for close in closes) / period
        band_width = sqrt(variance) * standard_deviations
        values.append(
            BollingerBandValue(
                date=bar.trading_date,
                upper=middle + band_width,
                middle=middle,
                lower=middle - band_width,
            )
        )

    return values


def latest_bollinger_band(
    bars: Sequence[DailyClose],
    *,
    period: int = 20,
    standard_deviations: float = 2,
) -> BollingerBandValue:
    if period <= 0:
        raise ValueError("Bollinger period must be greater than zero.")
    if not bars:
        raise ValueError("At least one bar is required.")

    latest_bar = bars[-1]
    if len(bars) < period:
        return BollingerBandValue(date=latest_bar.trading_date)

    closes = [item.close for item in bars[-period:]]
    middle = sum(closes) / period
    variance = sum((close - middle) ** 2 for close in closes) / period
    band_width = sqrt(variance) * standard_deviations
    return BollingerBandValue(
        date=latest_bar.trading_date,
        upper=middle + band_width,
        middle=middle,
        lower=middle - band_width,
    )


def calculate_rsi(
    bars: Sequence[DailyClose],
    *,
    period: int = 14,
) -> list[RsiValue]:
    if period <= 0:
        raise ValueError("RSI period must be greater than zero.")

    values = [RsiValue(date=bar.trading_date) for bar in bars]

    if len(bars) <= period:
        return values

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, period + 1):
        change = bars[index].close - bars[index - 1].close
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    values[period] = RsiValue(
        date=bars[period].trading_date,
        value=rsi_from_averages(average_gain, average_loss),
    )

    for index in range(period + 1, len(bars)):
        change = bars[index].close - bars[index - 1].close
        gain = max(change, 0)
        loss = max(-change, 0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        values[index] = RsiValue(
            date=bars[index].trading_date,
            value=rsi_from_averages(average_gain, average_loss),
        )

    return values


def rsi_state_from_bars(
    bars: Sequence[DailyClose],
    *,
    period: int = 14,
) -> RsiState:
    if period <= 0:
        raise ValueError("RSI period must be greater than zero.")
    if not bars:
        return RsiState(
            previous_close=None,
            average_gain=None,
            average_loss=None,
            observation_count=0,
            period=period,
        )
    if len(bars) <= period:
        return RsiState(
            previous_close=bars[-1].close,
            average_gain=None,
            average_loss=None,
            observation_count=len(bars),
            period=period,
        )

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, period + 1):
        change = bars[index].close - bars[index - 1].close
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    for index in range(period + 1, len(bars)):
        change = bars[index].close - bars[index - 1].close
        gain = max(change, 0)
        loss = max(-change, 0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period

    return RsiState(
        previous_close=bars[-1].close,
        average_gain=average_gain,
        average_loss=average_loss,
        observation_count=len(bars),
        period=period,
    )


def latest_rsi(
    state: RsiState,
    bar: DailyClose,
) -> RsiValue:
    if state.previous_close is None:
        return RsiValue(date=bar.trading_date)

    change = bar.close - state.previous_close
    gain = max(change, 0)
    loss = max(-change, 0)

    if state.average_gain is None or state.average_loss is None:
        return RsiValue(date=bar.trading_date)

    average_gain = ((state.average_gain * (state.period - 1)) + gain) / state.period
    average_loss = ((state.average_loss * (state.period - 1)) + loss) / state.period
    return RsiValue(
        date=bar.trading_date,
        value=rsi_from_averages(average_gain, average_loss),
    )


def rsi_from_averages(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))
