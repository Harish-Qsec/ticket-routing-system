import io
import logging

import pytest

from app.api.middleware import pick_request_id
from app.logging_config import configure_logging, request_id_var


@pytest.fixture
def log_output():
    """Configure logging and capture what the console handler would print."""
    configure_logging("DEBUG")
    handler = logging.getLogger("app").handlers[0]
    stream = io.StringIO()
    handler.setStream(stream)
    return stream


def test_configure_logging_can_run_twice_without_duplicate_handlers():
    configure_logging("INFO")
    configure_logging("INFO")

    assert len(logging.getLogger("app").handlers) == 1


def test_the_configured_level_is_applied():
    configure_logging("WARNING")

    assert logging.getLogger("app").level == logging.WARNING


def test_an_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        configure_logging("LOUD")


def test_log_lines_show_level_request_id_thread_and_message(log_output):
    token = request_id_var.set("abc123")
    try:
        logging.getLogger("app.demo").info("hello %s", "world")
    finally:
        request_id_var.reset(token)

    line = log_output.getvalue()
    assert "INFO" in line
    assert "[abc123]" in line
    assert "MainThread" in line
    assert "app.demo: hello world" in line


def test_outside_a_request_the_request_id_is_a_dash(log_output):
    logging.getLogger("app.demo").info("startup")

    assert "[-]" in log_output.getvalue()


def test_a_request_id_passed_with_the_record_wins(log_output):
    logging.getLogger("app.demo").info("x", extra={"request_id": "fixed-id"})

    assert "[fixed-id]" in log_output.getvalue()


def test_newlines_in_a_message_cannot_forge_extra_log_lines(log_output):
    logging.getLogger("app.demo").info("user sent: %s", "T-1\nINFO fake line")

    output = log_output.getvalue()
    assert len(output.splitlines()) == 1
    assert "T-1\\nINFO fake line" in output


def test_tracebacks_keep_their_line_breaks(log_output):
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("app.demo").exception("it failed")

    output = log_output.getvalue()
    assert len(output.splitlines()) > 1
    assert "Traceback" in output
    assert "RuntimeError: boom" in output


@pytest.mark.parametrize(
    "sent",
    ["trace-123", "A.b_c-9", "x" * 64],
    ids=["simple", "all-allowed-characters", "max-length"],
)
def test_a_safe_client_request_id_is_kept(sent):
    assert pick_request_id(sent) == sent


@pytest.mark.parametrize(
    "sent",
    [None, "", "has space", "new\nline", "x" * 65, "semi;colon", "\u00e9"],
    ids=["none", "empty", "space", "newline", "too-long", "semicolon", "non-ascii"],
)
def test_an_unsafe_or_missing_request_id_is_replaced(sent):
    generated = pick_request_id(sent)

    assert generated != sent
    assert len(generated) == 16