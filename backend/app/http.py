from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from app.options.types import OptionsDataUnavailable
from app.orders.errors import OrderServiceUnavailable, OrderServiceValidationError
from app.tickers import require_ticker


@contextmanager
def service_errors_as_http() -> Iterator[None]:
    """Translate service errors only around HTTP route operations."""
    try:
        yield
    except OrderServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except OrderServiceValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OptionsDataUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def required_ticker(ticker: str) -> str:
    try:
        return require_ticker(ticker)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Ticker is required.") from error
