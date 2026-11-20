"""Logging setup: one console handler, request IDs, and log-forging protection."""
import logging
import logging.config
import re
from contextvars import ContextVar

from app.config import VALID_LOG_LEVELS

# The ID of the HTTP request being handled in this context ("-" outside one).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class RequestIdFilter(logging.Filter):
    """Makes %(request_id)s available to the formatter on every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):  # a caller may pass it via extra=
            record.request_id = request_id_var.get()
        return True


class SafeFormatter(logging.Formatter):
    """Escapes control characters (newlines and the like) in the log MESSAGE.

    Without this, text a client controls could contain a newline followed by
    a fake log line ("log forging"). Tracebacks are appended separately and
    keep their line breaks.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:
        record.message = _CONTROL_CHARACTERS.sub(
            lambda match: match.group().encode("unicode_escape").decode("ascii"),
            record.message,
        )
        return super().formatMessage(record)


LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s [%(request_id)s] %(threadName)s "
    "%(name)s: %(message)s"
)


def configure_logging(level: str = "INFO") -> None:
    """Configure the "app" logger. Safe to call more than once."""
    level = level.upper()
    if level not in VALID_LOG_LEVELS:
        raise ValueError(f"Unknown log level {level!r}")
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,  # leave uvicorn's loggers alone
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {"standard": {"()": SafeFormatter, "fmt": LOG_FORMAT}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "filters": ["request_id"],
                }
            },
            "loggers": {
                # propagate=True keeps the records visible to pytest's caplog.
                "app": {"level": level, "handlers": ["console"], "propagate": True}
            },
        }
    )