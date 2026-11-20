"""Request middleware: a request ID for every request, and one access-log line."""
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request

from app.logging_config import request_id_var

access_logger = logging.getLogger("app.access")

# A client may send its own X-Request-ID, but only in this safe shape
# (otherwise it could smuggle newlines or huge text into our logs).
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def pick_request_id(client_value: str | None) -> str:
    """Use the client's ID if it is safe, otherwise generate a fresh one."""
    if client_value and _SAFE_REQUEST_ID.fullmatch(client_value):
        return client_value
    return uuid.uuid4().hex[:16]


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id_and_log(request: Request, call_next):
        request_id = pick_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id  # error handlers read it from here
        token = request_id_var.set(request_id)  # log lines read it from here
        started = time.perf_counter()
        status_code = 500  # what the client gets if an exception escapes
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            # Method, path and status only: never headers, query strings or bodies.
            access_logger.info(
                "%s %s -> %s (%.1f ms)",
                request.method, request.url.path, status_code, elapsed_ms,
            )
            request_id_var.reset(token)