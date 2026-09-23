from fastapi import APIRouter, HTTPException, Request

from app.options_trade_tracker.store import (
    OptionsTrade,
    OptionsTradeTracker,
    OptionsTradeTrackerDuplicateNameError,
    OptionsTradeTrackerNotFoundError,
    OptionsTradeTrackerValidationError,
)
from app.schemas import (
    OptionsTradeNotesRequest,
    OptionsTradeRowResponse,
    OptionsTradeRowsReplaceRequest,
    OptionsTradeStrategiesRequest,
    OptionsTradeStrategyOptionsResponse,
    OptionsTradeTrackerCreateRequest,
    OptionsTradeTrackerDetailResponse,
    OptionsTradeTrackerListResponse,
    OptionsTradeTrackerRenameRequest,
    OptionsTradeTrackerSummaryResponse,
)

router = APIRouter(prefix="/options-trade-trackers")


@router.get("", response_model=OptionsTradeTrackerListResponse)
def list_options_trade_trackers(request: Request) -> OptionsTradeTrackerListResponse:
    trackers = request.app.state.options_trade_tracker_store.list_trackers()
    return OptionsTradeTrackerListResponse(
        trackers=[tracker_summary_response(tracker) for tracker in trackers],
    )


@router.post("", response_model=OptionsTradeTrackerDetailResponse)
def create_options_trade_tracker(
    request: Request,
    tracker_request: OptionsTradeTrackerCreateRequest,
) -> OptionsTradeTrackerDetailResponse:
    try:
        tracker = request.app.state.options_trade_tracker_store.create_tracker(
            tracker_request.name,
        )
    except OptionsTradeTrackerDuplicateNameError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return tracker_detail_response(request, tracker)


@router.get(
    "/strategy-options",
    response_model=OptionsTradeStrategyOptionsResponse,
)
def list_options_trade_strategy_options(
    request: Request,
) -> OptionsTradeStrategyOptionsResponse:
    strategies = request.app.state.options_trade_tracker_store.list_strategy_options()
    return OptionsTradeStrategyOptionsResponse(strategies=strategies)


@router.put(
    "/strategy-options",
    response_model=OptionsTradeStrategyOptionsResponse,
)
def replace_options_trade_strategy_options(
    request: Request,
    strategies_request: OptionsTradeStrategiesRequest,
) -> OptionsTradeStrategyOptionsResponse:
    strategies = request.app.state.options_trade_tracker_store.replace_strategy_options(
        strategies_request.strategies,
    )
    return OptionsTradeStrategyOptionsResponse(strategies=strategies)


@router.get("/{tracker_id}", response_model=OptionsTradeTrackerDetailResponse)
def get_options_trade_tracker(
    request: Request,
    tracker_id: str,
) -> OptionsTradeTrackerDetailResponse:
    tracker = require_tracker(request, tracker_id)
    return tracker_detail_response(request, tracker)


@router.patch("/{tracker_id}", response_model=OptionsTradeTrackerDetailResponse)
def rename_options_trade_tracker(
    request: Request,
    tracker_id: str,
    tracker_request: OptionsTradeTrackerRenameRequest,
) -> OptionsTradeTrackerDetailResponse:
    try:
        tracker = request.app.state.options_trade_tracker_store.rename_tracker(
            tracker_id,
            tracker_request.name,
        )
    except OptionsTradeTrackerDuplicateNameError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except OptionsTradeTrackerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return tracker_detail_response(request, tracker)


@router.delete("/{tracker_id}", status_code=204)
def delete_options_trade_tracker(request: Request, tracker_id: str) -> None:
    try:
        request.app.state.options_trade_tracker_store.delete_tracker(tracker_id)
    except OptionsTradeTrackerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put(
    "/{tracker_id}/trades",
    response_model=OptionsTradeTrackerDetailResponse,
)
def replace_options_trade_tracker_trades(
    request: Request,
    tracker_id: str,
    trades_request: OptionsTradeRowsReplaceRequest,
) -> OptionsTradeTrackerDetailResponse:
    trades = [
        OptionsTrade(
            id=trade.id or "",
            tracker_id=tracker_id,
            display_order=trade.display_order,
            status=trade.status,
            strategy=trade.strategy,
            ticker=trade.ticker,
            month=trade.month,
            expiry_date=(
                trade.expiry_date.isoformat() if trade.expiry_date else None
            ),
            size=trade.size,
            strike_price=trade.strike_price,
            credit_debit=trade.credit_debit,
            exit=trade.exit,
            created_at="",
            updated_at="",
        )
        for trade in trades_request.trades
    ]

    try:
        request.app.state.options_trade_tracker_store.replace_trades(
            tracker_id,
            trades,
        )
    except OptionsTradeTrackerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OptionsTradeTrackerValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    tracker = require_tracker(request, tracker_id)
    return tracker_detail_response(request, tracker)


@router.put(
    "/{tracker_id}/notes",
    response_model=OptionsTradeTrackerDetailResponse,
)
def update_options_trade_tracker_notes(
    request: Request,
    tracker_id: str,
    notes_request: OptionsTradeNotesRequest,
) -> OptionsTradeTrackerDetailResponse:
    try:
        tracker = request.app.state.options_trade_tracker_store.update_notes(
            tracker_id,
            notes_request.notes,
        )
    except OptionsTradeTrackerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return tracker_detail_response(request, tracker)


def require_tracker(request: Request, tracker_id: str) -> OptionsTradeTracker:
    tracker = request.app.state.options_trade_tracker_store.get_tracker(tracker_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Tracker not found.")
    return tracker


def tracker_detail_response(
    request: Request,
    tracker: OptionsTradeTracker,
) -> OptionsTradeTrackerDetailResponse:
    store = request.app.state.options_trade_tracker_store
    trades = store.list_trades(tracker.id)
    strategies = store.list_strategy_options()
    return OptionsTradeTrackerDetailResponse(
        tracker=tracker_summary_response(tracker),
        trades=[trade_response(trade) for trade in trades],
        notes=tracker.notes,
        strategy_options=strategies,
    )


def tracker_summary_response(
    tracker: OptionsTradeTracker,
) -> OptionsTradeTrackerSummaryResponse:
    return OptionsTradeTrackerSummaryResponse(
        id=tracker.id,
        name=tracker.name,
        created_at=tracker.created_at,
        updated_at=tracker.updated_at,
    )


def trade_response(trade: OptionsTrade) -> OptionsTradeRowResponse:
    return OptionsTradeRowResponse(
        id=trade.id,
        display_order=trade.display_order,
        status=trade.status,
        strategy=trade.strategy,
        ticker=trade.ticker,
        month=trade.month,
        expiry_date=trade.expiry_date,
        size=trade.size,
        strike_price=trade.strike_price,
        credit_debit=trade.credit_debit,
        exit=trade.exit,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )
