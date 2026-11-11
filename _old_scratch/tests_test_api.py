from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_list_ticket() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/tickets",
            json={"subject": "Cannot sign in", "description": "Login returns an error."},
        )
        assert created.status_code == 201
        ticket = created.json()

        listed = client.get("/tickets")

    assert ticket["subject"] == "Cannot sign in"
    assert ticket["status"] == "queued"
    assert any(item["id"] == ticket["id"] for item in listed.json())