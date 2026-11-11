import pytest
from pydantic import ValidationError

from app.exceptions import (
    DuplicateTicketError,
    InvalidStatusTransitionError,
    TicketNotFoundError,
)
from app.models.enums import TicketStatus


def advance(service, ticket_id, *statuses):
    """Walk a ticket through several status changes."""
    for status in statuses:
        service.update_status(ticket_id, status)


def test_create_ticket_sets_defaults(ticket_service, make_ticket_data):
    ticket = ticket_service.create_ticket(make_ticket_data())

    assert ticket.ticket_id == "T-1"
    assert ticket.status == TicketStatus.OPEN
    assert ticket.assigned_engineer_id is None
    assert ticket.created_at.tzinfo is not None  # timezone-aware


def test_get_ticket_returns_created_ticket(ticket_service, make_ticket_data):
    created = ticket_service.create_ticket(make_ticket_data())
    assert ticket_service.get_ticket("T-1") is created


def test_get_missing_ticket_raises(ticket_service):
    with pytest.raises(TicketNotFoundError):
        ticket_service.get_ticket("nope")


def test_list_tickets_keeps_creation_order(ticket_service, make_ticket_data):
    for ticket_id in ("T-1", "T-2", "T-3"):
        ticket_service.create_ticket(make_ticket_data(ticket_id))

    ids = [t.ticket_id for t in ticket_service.list_tickets()]
    assert ids == ["T-1", "T-2", "T-3"]


def test_duplicate_ticket_id_is_rejected(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data("T-1", title="Original"))

    with pytest.raises(DuplicateTicketError):
        ticket_service.create_ticket(make_ticket_data("T-1", title="Imposter"))

    assert len(ticket_service.list_tickets()) == 1
    assert ticket_service.get_ticket("T-1").title == "Original"


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticket_id": ""},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"description": ""},
        {"priority": "URGENT"},
        {"category": "COFFEE"},
    ],
    ids=[
        "empty-id",
        "empty-title",
        "blank-title",
        "title-too-long",
        "empty-description",
        "unknown-priority",
        "unknown-category",
    ],
)
def test_invalid_ticket_data_is_rejected(make_ticket_data, overrides):
    with pytest.raises(ValidationError):
        make_ticket_data(**overrides)


def test_full_status_lifecycle(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())
    advance(
        ticket_service,
        "T-1",
        TicketStatus.QUEUED,
        TicketStatus.PROCESSING,
        TicketStatus.ASSIGNED,
        TicketStatus.RESOLVED,
    )
    assert ticket_service.get_ticket("T-1").status == TicketStatus.RESOLVED


def test_illegal_transition_is_rejected_and_status_unchanged(
    ticket_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())

    with pytest.raises(InvalidStatusTransitionError):
        ticket_service.update_status("T-1", TicketStatus.RESOLVED)

    assert ticket_service.get_ticket("T-1").status == TicketStatus.OPEN


def test_resolved_is_terminal(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())
    advance(
        ticket_service, "T-1",
        TicketStatus.QUEUED, TicketStatus.PROCESSING,
        TicketStatus.ASSIGNED, TicketStatus.RESOLVED,
    )
    with pytest.raises(InvalidStatusTransitionError):
        ticket_service.update_status("T-1", TicketStatus.QUEUED)


def test_failed_ticket_can_be_requeued(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())
    advance(
        ticket_service, "T-1",
        TicketStatus.QUEUED, TicketStatus.FAILED, TicketStatus.QUEUED,
    )
    assert ticket_service.get_ticket("T-1").status == TicketStatus.QUEUED


def test_update_status_of_missing_ticket_raises(ticket_service):
    with pytest.raises(TicketNotFoundError):
        ticket_service.update_status("nope", TicketStatus.QUEUED)


def test_assign_engineer_sets_id_and_status(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())
    advance(ticket_service, "T-1", TicketStatus.QUEUED, TicketStatus.PROCESSING)

    ticket = ticket_service.assign_engineer("T-1", "E-1")

    assert ticket.assigned_engineer_id == "E-1"
    assert ticket.status == TicketStatus.ASSIGNED


def test_assign_engineer_requires_processing_status(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())  # still OPEN

    with pytest.raises(InvalidStatusTransitionError):
        ticket_service.assign_engineer("T-1", "E-1")

    assert ticket_service.get_ticket("T-1").assigned_engineer_id is None