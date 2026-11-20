import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.errors import register_error_handlers
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


def client_that_raises(error: Exception) -> TestClient:
    """A tiny app whose only endpoint raises the given error."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise error

    # raise_server_exceptions=False: show us the 500 response instead of
    # letting the test client re-raise the error.
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (TicketNotFoundError("T-1"), 404),
        (EngineerNotFoundError("E-1"), 404),
        (DuplicateTicketError("T-1"), 409),
        (DuplicateEngineerError("E-1"), 409),
        (InvalidStatusTransitionError("OPEN", "RESOLVED"), 409),
        (NoAvailableEngineerError("NETWORK"), 409),
        (QueueFullError(5), 503),
    ],
    ids=["ticket-404", "engineer-404", "dup-ticket-409", "dup-engineer-409",
         "bad-transition-409", "no-engineer-409", "queue-full-503"],
)
def test_each_domain_error_maps_to_the_right_http_status(error, expected_status):
    response = client_that_raises(error).get("/boom")

    body = response.json()
    assert response.status_code == expected_status
    assert body["detail"] == str(error)
    assert response.headers["x-request-id"] == body["request_id"]


def test_only_queue_full_asks_the_client_to_retry_later():
    assert client_that_raises(QueueFullError(5)).get("/boom").headers["retry-after"] == "5"
    assert "retry-after" not in client_that_raises(TicketNotFoundError("T-1")).get("/boom").headers


def test_an_unmapped_domain_error_becomes_a_generic_500():
    response = client_that_raises(TicketSystemError("secret internals")).get("/boom")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "secret" not in response.text


def test_an_unexpected_exception_becomes_a_generic_500_and_is_logged(caplog):
    caplog.set_level(logging.DEBUG, logger="app")

    response = client_that_raises(RuntimeError("password=hunter2")).get("/boom")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "hunter2" not in response.text  # never returned to the client
    errors = [
        r for r in caplog.records
        if r.name == "app.api.errors" and r.levelno == logging.ERROR
    ]
    assert errors
    assert errors[0].exc_info is not None  # but the traceback is in the log


def test_a_busy_database_becomes_a_503_without_leaking_sql():
    error = OperationalError(
        "SELECT secret FROM tickets", {"p": "hunter2"}, Exception("database is locked")
    )

    response = client_that_raises(error).get("/boom")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert response.json()["detail"] == "The database is temporarily unavailable"
    assert "SELECT" not in response.text
    assert "hunter2" not in response.text


def test_any_other_database_error_becomes_a_generic_500():
    response = client_that_raises(SQLAlchemyError("boom hunter2")).get("/boom")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "hunter2" not in response.text


def test_an_unknown_url_uses_the_standard_error_shape():
    response = client_that_raises(RuntimeError("unused")).get("/does-not-exist")

    assert response.status_code == 404
    assert set(response.json()) == {"detail", "request_id"}


def test_a_wrong_method_keeps_the_allow_header():
    response = client_that_raises(RuntimeError("unused")).post("/boom")

    assert response.status_code == 405
    assert "GET" in response.headers["allow"]