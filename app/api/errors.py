"""Turns every kind of failure into ONE consistent JSON error shape.

Every error response looks like:
    {"detail": "<short human-readable summary>", "request_id": "<id>"}
Validation errors add an "errors" list. Stack traces, SQL and the values a
client sent are logged or dropped, but never returned.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import (
    DuplicateEngineerError,
    DuplicateTicketError,
    EngineerNotFoundError,
    InvalidStatusTransitionError,
    NoAvailableEngineerError,
    QueueFullError,
    TicketNotFoundError,
    TicketSystemError,
)

logger = logging.getLogger(__name__)

_STATUS_BY_ERROR: list[tuple[type[TicketSystemError], int]] = [
    (TicketNotFoundError, status.HTTP_404_NOT_FOUND),
    (EngineerNotFoundError, status.HTTP_404_NOT_FOUND),
    (DuplicateTicketError, status.HTTP_409_CONFLICT),
    (DuplicateEngineerError, status.HTTP_409_CONFLICT),
    (InvalidStatusTransitionError, status.HTTP_409_CONFLICT),
    (NoAvailableEngineerError, status.HTTP_409_CONFLICT),
    (QueueFullError, status.HTTP_503_SERVICE_UNAVAILABLE),
]

GENERIC_500 = "Internal server error"


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _log(request: Request, level: int, message: str, *args, exc_info=None) -> None:
    logger.log(
        level, message, *args,
        exc_info=exc_info, extra={"request_id": _request_id(request)},
    )


def _error_response(
    request: Request, status_code: int, detail: str, *, headers=None, **extra
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = {"X-Request-ID": request_id}
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "request_id": request_id, **extra},
        headers=response_headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    async def handle_domain_error(request: Request, exc: TicketSystemError):
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        for error_type, code in _STATUS_BY_ERROR:
            if isinstance(exc, error_type):
                status_code = code
                break

        if status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            # A domain error nobody mapped is a bug: log it, hide the details.
            _log(request, logging.ERROR, "unmapped domain error %s",
                 type(exc).__name__, exc_info=exc)
            return _error_response(request, status_code, GENERIC_500)

        level = logging.WARNING if status_code >= 500 else logging.INFO
        _log(request, level, "request rejected (HTTP %s): %s", status_code, exc)
        headers = {"Retry-After": "5"} if isinstance(exc, QueueFullError) else None
        return _error_response(request, status_code, str(exc), headers=headers)

    async def handle_validation_error(request: Request, exc: RequestValidationError):
        # Only the field names and the rule that failed: never the submitted values.
        errors = [
            {"field": ".".join(str(part) for part in error["loc"]),
             "message": error["msg"]}
            for error in exc.errors()
        ]
        _log(request, logging.INFO, "request validation failed on: %s",
             ", ".join(error["field"] for error in errors))
        return _error_response(
            request, 422, "Request validation failed", errors=errors
        )

    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        # Unknown URL (404), wrong method (405), and so on.
        _log(request, logging.INFO, "HTTP %s: %s", exc.status_code, exc.detail)
        return _error_response(
            request, exc.status_code, str(exc.detail), headers=exc.headers
        )

    async def handle_database_error(request: Request, exc: SQLAlchemyError):
        if isinstance(exc, OperationalError):  # locked, unreachable, disk full...
            _log(request, logging.WARNING, "database unavailable or busy", exc_info=exc)
            return _error_response(
                request, status.HTTP_503_SERVICE_UNAVAILABLE,
                "The database is temporarily unavailable",
                headers={"Retry-After": "2"},
            )
        _log(request, logging.ERROR, "unexpected database error", exc_info=exc)
        return _error_response(request, 500, GENERIC_500)

    async def handle_unexpected_error(request: Request, exc: Exception):
        _log(request, logging.ERROR, "unhandled %s", type(exc).__name__, exc_info=exc)
        return _error_response(request, 500, GENERIC_500)

    # Starlette picks the handler by walking the exception's class hierarchy,
    # so each registration below also covers that class's subclasses.
    app.add_exception_handler(TicketSystemError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(SQLAlchemyError, handle_database_error)
    app.add_exception_handler(Exception, handle_unexpected_error)