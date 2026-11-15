"""Translates our domain exceptions into HTTP responses in ONE place."""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

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

_STATUS_BY_ERROR: list[tuple[type[TicketSystemError], int]] = [
    (TicketNotFoundError, status.HTTP_404_NOT_FOUND),
    (EngineerNotFoundError, status.HTTP_404_NOT_FOUND),
    (DuplicateTicketError, status.HTTP_409_CONFLICT),
    (DuplicateEngineerError, status.HTTP_409_CONFLICT),
    (InvalidStatusTransitionError, status.HTTP_409_CONFLICT),
    (NoAvailableEngineerError, status.HTTP_409_CONFLICT),
    (QueueFullError, status.HTTP_503_SERVICE_UNAVAILABLE),
]


def register_error_handlers(app: FastAPI) -> None:
    async def handle_domain_error(request: Request, exc: TicketSystemError) -> JSONResponse:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        for error_type, code in _STATUS_BY_ERROR:
            if isinstance(exc, error_type):
                status_code = code
                break
        headers = {"Retry-After": "5"} if isinstance(exc, QueueFullError) else None
        return JSONResponse(
            status_code=status_code, content={"detail": str(exc)}, headers=headers
        )

    # Starlette looks handlers up along the exception's class hierarchy, so
    # registering the base class covers every subclass.
    app.add_exception_handler(TicketSystemError, handle_domain_error)