from collections import defaultdict
from datetime import date

from fastapi import APIRouter, HTTPException, Request

from app.day_trading_tracker.store import (
    DayTradingRow,
    DayTradingTrackerValidationError,
)
from app.schemas import (
    DAY_TRADING_MIN_DATE,
    DayTradingDayResponse,
    DayTradingMonthResponse,
    DayTradingRowResponse,
    DayTradingRowsReplaceRequest,
    MONTH_KEY_PATTERN,
)

router = APIRouter(prefix="/day-trading-tracker")


@router.get("/months/{month}", response_model=DayTradingMonthResponse)
def get_day_trading_month(request: Request, month: str) -> DayTradingMonthResponse:
    validate_month(month)
    rows = request.app.state.day_trading_tracker_store.list_month_rows(month)
    rows_by_date: dict[str, list[DayTradingRow]] = defaultdict(list)
    for row in rows:
        rows_by_date[row.trade_date].append(row)

    return DayTradingMonthResponse(
        month=month,
        days=[
            DayTradingDayResponse(
                date=trade_date,
                trades=[day_trading_row_response(row) for row in day_rows],
            )
            for trade_date, day_rows in sorted(rows_by_date.items())
        ],
    )


@router.put(
    "/days/{trade_date}/trades",
    response_model=DayTradingDayResponse,
)
def replace_day_trading_trades(
    request: Request,
    trade_date: str,
    trades_request: DayTradingRowsReplaceRequest,
) -> DayTradingDayResponse:
    validate_trade_date(trade_date)
    rows = [
        DayTradingRow(
            id=trade.id or "",
            trade_date=trade_date,
            display_order=trade.display_order,
            buy=trade.buy,
            sell=trade.sell,
            size=trade.size,
            fee=trade.fee,
            created_at="",
            updated_at="",
        )
        for trade in trades_request.trades
    ]

    try:
        saved_rows = request.app.state.day_trading_tracker_store.replace_day_rows(
            trade_date,
            rows,
        )
    except DayTradingTrackerValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return DayTradingDayResponse(
        date=trade_date,
        trades=[day_trading_row_response(row) for row in saved_rows],
    )


def validate_month(month: str) -> None:
    if not MONTH_KEY_PATTERN.fullmatch(month):
        raise HTTPException(status_code=422, detail="month must use YYYY-MM format.")

    first_day = date.fromisoformat(f"{month}-01")
    min_month = date.fromisoformat(DAY_TRADING_MIN_DATE).replace(day=1)
    current_month = date.today().replace(day=1)
    if first_day < min_month:
        raise HTTPException(status_code=422, detail="month is before August 2026.")
    if first_day > current_month:
        raise HTTPException(status_code=422, detail="month is after the current month.")


def validate_trade_date(value: str) -> None:
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="trade_date must use YYYY-MM-DD format.",
        ) from error

    min_date = date.fromisoformat(DAY_TRADING_MIN_DATE)
    if parsed_date < min_date:
        raise HTTPException(status_code=422, detail="date is before August 1, 2026.")
    if parsed_date > date.today():
        raise HTTPException(status_code=422, detail="date is after the current date.")


def day_trading_row_response(row: DayTradingRow) -> DayTradingRowResponse:
    return DayTradingRowResponse(
        id=row.id,
        display_order=row.display_order,
        buy=row.buy,
        sell=row.sell,
        size=row.size,
        fee=row.fee,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
