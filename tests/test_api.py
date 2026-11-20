import logging
import re
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import sqlite_url
from app.main import create_app



# ---------- request IDs, error shape and logging ----------


def test_every_response_carries_a_request_id_header(client):
    response = client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{16}", response.headers["x-request-id"])


def test_a_safe_client_request_id_is_echoed_back(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["x-request-id"] == "trace-123"


def test_an_unsafe_client_request_id_is_replaced(client):
    sent = "bad id with spaces!"

    response = client.get("/health", headers={"X-Request-ID": sent})

    assert response.headers["x-request-id"] != sent
    assert re.fullmatch(r"[0-9a-f]{16}", response.headers["x-request-id"])


def test_error_bodies_carry_the_same_request_id_as_the_header(client):
    response = client.get("/tickets/nope")

    assert response.status_code == 404
    body = response.json()
    assert body["request_id"] == response.headers["x-request-id"]
    assert set(body) == {"detail", "request_id"}


def test_validation_errors_use_the_standard_shape_and_never_echo_the_input(client):
    secret = "SECRET-PRIORITY-1"

    response = client.post("/tickets", json=ticket_payload(priority=secret))

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Request validation failed"
    assert any(error["field"] == "body.priority" for error in body["errors"])
    assert secret not in response.text


def test_validation_failures_are_logged_without_the_input_values(client, caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    secret = "SECRET-PRIORITY-2"

    client.post("/tickets", json=ticket_payload(priority=secret))

    assert any("body.priority" in r.getMessage() for r in caplog.records)
    assert secret not in caplog.text


def test_every_request_gets_one_access_log_line(client, caplog):
    caplog.set_level(logging.DEBUG, logger="app")

    client.get("/health")

    lines = [r.getMessage() for r in caplog.records if r.name == "app.access"]
    assert len(lines) == 1
    assert lines[0].startswith("GET /health -> 200")


@pytest.mark.parametrize(
    "bad_id",
    ["T 1", "T/1", "T-1\nFORGED", "T-1;DROP", "t\u00efcket"],
    ids=["space", "slash", "newline", "semicolon", "non-ascii"],
)
def test_unsafe_ticket_ids_are_rejected_by_the_api(client, bad_id):
    response = client.post("/tickets", json=ticket_payload(bad_id))

    assert response.status_code == 422
    assert client.get("/tickets").json() == []

@pytest.fixture
def make_client(tmp_path):
    """Build running apps (workers included), each with its own database file."""
    clients = []

    def _make(**overrides) -> TestClient:
        settings = Settings(
            database_url=sqlite_url(tmp_path / f"api-{len(clients)}.db"),
            num_workers=2,
            poll_timeout=0.02,
            **overrides,
        )
        client = TestClient(create_app(settings))
        client.__enter__()  # runs startup: creates the tables, starts the workers
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)  # runs shutdown: stops the workers


@pytest.fixture
def client(make_client):
    return make_client()


def ticket_payload(ticket_id="T-1", **overrides):
    payload = {
        "ticket_id": ticket_id,
        "title": "VPN not connecting",
        "description": "Cannot connect to the office VPN from home.",
        "priority": "HIGH",
        "category": "NETWORK",
    }
    payload.update(overrides)
    return payload


def engineer_payload(engineer_id="E-1", **overrides):
    payload = {"engineer_id": engineer_id, "name": "Asha", "skills": ["NETWORK"]}
    payload.update(overrides)
    return payload


def wait_for_status(client, ticket_id, expected, timeout=10.0):
    """Workers run in the background, so poll until the ticket reaches a status."""
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/tickets/{ticket_id}").json()
        if body["status"] == expected or time.monotonic() > deadline:
            return body
        time.sleep(0.02)


# ---------- health and docs ----------


def test_health_reports_workers_and_queue(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["workers_running"] is True
    assert body["queue_size"] == 0


def test_openapi_lists_every_required_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) >= {
        "/tickets",
        "/tickets/{ticket_id}",
        "/tickets/{ticket_id}/status",
        "/tickets/{ticket_id}/process",
        "/engineers",
    }


# ---------- tickets ----------


def test_create_ticket_returns_201_with_location(client):
    response = client.post("/tickets", json=ticket_payload())

    assert response.status_code == 201
    assert response.headers["location"] == "/tickets/T-1"
    body = response.json()
    assert body["ticket_id"] == "T-1"
    assert body["status"] == "OPEN"
    assert body["assigned_engineer_id"] is None
    assert "created_at" in body


def test_create_duplicate_ticket_returns_409(client):
    assert client.post("/tickets", json=ticket_payload()).status_code == 201

    response = client.post("/tickets", json=ticket_payload())

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"priority": "URGENT"},
        {"category": "COFFEE"},
        {"ticket_id": ""},
    ],
    ids=["empty-title", "blank-title", "long-title", "bad-priority",
         "bad-category", "empty-id"],
)
def test_create_ticket_with_invalid_data_returns_422(client, overrides):
    response = client.post("/tickets", json=ticket_payload(**overrides))

    assert response.status_code == 422
    assert client.get("/tickets").json() == []  # nothing was stored


def test_create_ticket_with_missing_field_returns_422(client):
    payload = ticket_payload()
    del payload["description"]

    assert client.post("/tickets", json=payload).status_code == 422


def test_get_ticket_returns_it(client):
    client.post("/tickets", json=ticket_payload())

    response = client.get("/tickets/T-1")

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "T-1"


def test_get_missing_ticket_returns_404(client):
    response = client.get("/tickets/nope")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_list_tickets_keeps_creation_order(client):
    for ticket_id in ("T-1", "T-2", "T-3"):
        client.post("/tickets", json=ticket_payload(ticket_id))

    ids = [t["ticket_id"] for t in client.get("/tickets").json()]

    assert ids == ["T-1", "T-2", "T-3"]


# ---------- engineers ----------


def test_add_engineer_returns_201_with_sorted_skills(client):
    response = client.post(
        "/engineers", json=engineer_payload(skills=["NETWORK", "ACCESS"])
    )

    assert response.status_code == 201
    body = response.json()
    assert body["skills"] == ["ACCESS", "NETWORK"]
    assert body["is_available"] is True


def test_add_duplicate_engineer_returns_409(client):
    assert client.post("/engineers", json=engineer_payload()).status_code == 201

    assert client.post("/engineers", json=engineer_payload()).status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [{"skills": []}, {"skills": ["COFFEE"]}, {"name": "  "}, {"engineer_id": ""}],
    ids=["no-skills", "bad-skill", "blank-name", "empty-id"],
)
def test_add_engineer_with_invalid_data_returns_422(client, overrides):
    response = client.post("/engineers", json=engineer_payload(**overrides))

    assert response.status_code == 422


def test_list_engineers_keeps_insertion_order(client):
    client.post("/engineers", json=engineer_payload("E-1"))
    client.post("/engineers", json=engineer_payload("E-2"))

    ids = [e["engineer_id"] for e in client.get("/engineers").json()]

    assert ids == ["E-1", "E-2"]


# ---------- processing ----------


def test_process_unknown_ticket_returns_404(client):
    assert client.post("/tickets/nope/process").status_code == 404


def test_process_returns_202_and_a_worker_assigns_an_engineer(client):
    client.post("/engineers", json=engineer_payload("E-1"))
    client.post("/tickets", json=ticket_payload())

    response = client.post("/tickets/T-1/process")

    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    body = wait_for_status(client, "T-1", "ASSIGNED")
    assert body["status"] == "ASSIGNED"
    assert body["assigned_engineer_id"] == "E-1"
    assert client.get("/engineers").json()[0]["is_available"] is False


def test_processing_the_same_ticket_twice_returns_409(client):
    client.post("/engineers", json=engineer_payload("E-1"))
    client.post("/tickets", json=ticket_payload())
    assert client.post("/tickets/T-1/process").status_code == 202

    assert client.post("/tickets/T-1/process").status_code == 409


def test_ticket_without_an_engineer_fails_and_can_be_retried(client):
    client.post("/tickets", json=ticket_payload())
    assert client.post("/tickets/T-1/process").status_code == 202
    assert wait_for_status(client, "T-1", "FAILED")["status"] == "FAILED"

    client.post("/engineers", json=engineer_payload("E-1"))
    assert client.post("/tickets/T-1/process").status_code == 202  # FAILED -> QUEUED

    assert wait_for_status(client, "T-1", "ASSIGNED")["status"] == "ASSIGNED"


def test_full_queue_returns_503_with_retry_after(make_client):
    client = make_client(queue_maxsize=1)
    # Park the workers so nothing drains the queue.
    client.app.state.container.pool.stop(drain=False, timeout=2.0)
    client.post("/tickets", json=ticket_payload("T-1"))
    client.post("/tickets", json=ticket_payload("T-2"))
    assert client.post("/tickets/T-1/process").status_code == 202

    response = client.post("/tickets/T-2/process")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert client.get("/tickets/T-2").json()["status"] == "FAILED"


# ---------- resolving ----------


def test_resolving_a_ticket_frees_its_engineer(client):
    client.post("/engineers", json=engineer_payload("E-1"))
    client.post("/tickets", json=ticket_payload())
    client.post("/tickets/T-1/process")
    wait_for_status(client, "T-1", "ASSIGNED")

    response = client.put("/tickets/T-1/status", json={"status": "RESOLVED"})

    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"
    assert client.get("/engineers").json()[0]["is_available"] is True


@pytest.mark.parametrize(
    "status_value", ["OPEN", "QUEUED", "PROCESSING", "ASSIGNED", "FAILED", "BOGUS"]
)
def test_clients_cannot_set_system_managed_statuses(client, status_value):
    client.post("/tickets", json=ticket_payload())

    response = client.put("/tickets/T-1/status", json={"status": status_value})

    assert response.status_code == 422
    assert client.get("/tickets/T-1").json()["status"] == "OPEN"


def test_resolving_an_unassigned_ticket_returns_409(client):
    client.post("/tickets", json=ticket_payload())  # still OPEN

    response = client.put("/tickets/T-1/status", json={"status": "RESOLVED"})

    assert response.status_code == 409
    assert client.get("/tickets/T-1").json()["status"] == "OPEN"


def test_resolving_an_unknown_ticket_returns_404(client):
    response = client.put("/tickets/nope/status", json={"status": "RESOLVED"})

    assert response.status_code == 404


# ---------- the whole pipeline through HTTP ----------


def test_many_tickets_flow_through_the_api(client):
    total = 20
    for n in range(total):
        client.post("/engineers", json=engineer_payload(f"E-{n}"))
        client.post("/tickets", json=ticket_payload(f"T-{n}"))
    for n in range(total):
        assert client.post(f"/tickets/T-{n}/process").status_code == 202
    for n in range(total):
        wait_for_status(client, f"T-{n}", "ASSIGNED")

    tickets = client.get("/tickets").json()

    assert len(tickets) == total
    assert all(t["status"] == "ASSIGNED" for t in tickets)
    assert len({t["assigned_engineer_id"] for t in tickets}) == total



# ---------- more edge cases ----------


def test_whitespace_around_text_fields_is_stripped(client):
    response = client.post("/tickets", json=ticket_payload(title="  VPN down  "))

    assert response.status_code == 201
    assert response.json()["title"] == "VPN down"


def test_a_resolved_ticket_cannot_be_processed_again(client):
    client.post("/engineers", json=engineer_payload("E-1"))
    client.post("/tickets", json=ticket_payload())
    client.post("/tickets/T-1/process")
    wait_for_status(client, "T-1", "ASSIGNED")
    client.put("/tickets/T-1/status", json={"status": "RESOLVED"})

    assert client.post("/tickets/T-1/process").status_code == 409


def test_wrong_http_method_returns_405(client):
    assert client.get("/tickets/T-1/process").status_code == 405


def test_malformed_json_returns_422(client):
    response = client.post(
        "/tickets", content="{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422


def test_queued_tickets_survive_an_application_restart(tmp_path):
    settings = Settings(
        database_url=sqlite_url(tmp_path / "restart.db"),
        num_workers=1,
        poll_timeout=0.02,
    )

    with TestClient(create_app(settings)) as first_server:
        first_server.post("/engineers", json=engineer_payload("E-1"))
        first_server.post("/tickets", json=ticket_payload("T-1"))
        # Stop the workers so nothing processes the ticket before the "crash".
        first_server.app.state.container.pool.stop(drain=False, timeout=2.0)
        assert first_server.post("/tickets/T-1/process").status_code == 202
    # Leaving the block shut the server down with T-1 still QUEUED in the database.

    with TestClient(create_app(settings)) as second_server:  # a brand-new server
        body = wait_for_status(second_server, "T-1", "ASSIGNED")
        assert body["status"] == "ASSIGNED"