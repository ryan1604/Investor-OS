import pytest

from app.options.indicators import (
    DailyClose,
    calculate_bollinger_bands,
    calculate_rsi,
)


def bars_from_closes(closes: list[float]) -> list[DailyClose]:
    return [
        DailyClose(
            trading_date=f"2026-05-{index + 1:02d}",
            close=close,
        )
        for index, close in enumerate(closes)
    ]


def test_bollinger_bands_return_missing_values_before_warmup():
    values = calculate_bollinger_bands(bars_from_closes([1, 2, 3]))

    assert values == [
        values[0].__class__(date="2026-05-01"),
        values[1].__class__(date="2026-05-02"),
        values[2].__class__(date="2026-05-03"),
    ]


def test_bollinger_bands_use_twenty_period_sma_and_two_standard_deviations():
    values = calculate_bollinger_bands(bars_from_closes(list(range(1, 21))))
    final_value = values[-1]

    assert final_value.date == "2026-05-20"
    assert final_value.middle == pytest.approx(10.5)
    assert final_value.upper == pytest.approx(22.032562594670797)
    assert final_value.lower == pytest.approx(-1.032562594670797)


def test_bollinger_bands_continue_rolling_after_warmup():
    values = calculate_bollinger_bands(bars_from_closes(list(range(1, 22))))
    final_value = values[-1]

    assert final_value.date == "2026-05-21"
    assert final_value.middle == pytest.approx(11.5)
    assert final_value.upper == pytest.approx(23.032562594670797)
    assert final_value.lower == pytest.approx(-0.03256259467079664)


def test_rsi_returns_missing_values_until_fourteen_changes_exist():
    values = calculate_rsi(bars_from_closes(list(range(1, 15))))

    assert [value.value for value in values] == [None] * 14


def test_rsi_uses_fourteen_period_wilder_smoothing():
    closes = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
        46.00,
    ]

    values = calculate_rsi(bars_from_closes(closes))

    assert values[13].value is None
    assert values[14].value == pytest.approx(70.46413502109705)
    assert values[15].value == pytest.approx(66.24961855355505)


def test_rsi_returns_one_hundred_when_average_loss_is_zero():
    values = calculate_rsi(bars_from_closes(list(range(1, 16))))

    assert values[-1].value == 100


def test_indicators_reject_invalid_periods():
    bars = bars_from_closes([1, 2, 3])

    with pytest.raises(ValueError):
        calculate_bollinger_bands(bars, period=0)

    with pytest.raises(ValueError):
        calculate_rsi(bars, period=0)
