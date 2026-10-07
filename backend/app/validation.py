"""JSON-safe request validation errors.

Python's JSON parser accepts `Infinity` and `NaN`, and FastAPI's default 422
response echoes each invalid input, which then fails to encode and turns the
422 into a 500. This handler returns the same response with non-finite
numbers in the echoed input written as strings.
"""

import math
from typing import Any

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def json_safe_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [json_safe(error) for error in exc.errors()]
    return await request_validation_exception_handler(
        request,
        RequestValidationError(errors, body=json_safe(exc.body)),
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value
