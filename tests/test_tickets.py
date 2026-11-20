import pytest
from pydantic import ValidationError
from app.models.enums import TicketCategory, TicketPriority, TicketStatus
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
    found = ticket_service.get_ticket("T-1")

    # Each call gets its own session, so these are two separate objects
    # describing the same row (compare values, not identity).
    assert found.ticket_id == created.ticket_id
    assert found.title == created.title

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


def test_assign_engineer_sets_id_and_status(
    ticket_service, engineer_service, make_ticket_data, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1"))  # the FK needs a real engineer
    ticket_service.create_ticket(make_ticket_data())
    advance(ticket_service, "T-1", TicketStatus.QUEUED, TicketStatus.PROCESSING)

    ticket = ticket_service.assign_engineer("T-1", "E-1")

    assert ticket.assigned_engineer_id == "E-1"
    assert ticket.status == TicketStatus.ASSIGNED


def test_assign_unknown_engineer_is_rejected_by_the_database(
    ticket_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    advance(ticket_service, "T-1", TicketStatus.QUEUED, TicketStatus.PROCESSING)

    with pytest.raises(EngineerNotFoundError):
        ticket_service.assign_engineer("T-1", "ghost")

    ticket = ticket_service.get_ticket("T-1")
    assert ticket.status == TicketStatus.PROCESSING
    assert ticket.assigned_engineer_id is None


def test_assign_engineer_requires_processing_status(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())  # still OPEN

    with pytest.raises(InvalidStatusTransitionError):
        ticket_service.assign_engineer("T-1", "E-1")

    assert ticket_service.get_ticket("T-1").assigned_engineer_id is None

from app.exceptions import (
    DuplicateTicketError,
    EngineerNotFoundError,
    InvalidStatusTransitionError,
    TicketNotFoundError,
)


def test_longest_allowed_values_are_accepted(make_ticket_data):
    data = make_ticket_data("x" * 50, title="t" * 200, description="d" * 2000)

    assert len(data.ticket_id) == 50
    assert len(data.title) == 200
    assert len(data.description) == 2000


@pytest.mark.parametrize(
    "overrides",
    [{"ticket_id": "x" * 51}, {"description": "d" * 2001}],
    ids=["id-too-long", "description-too-long"],
)
def test_values_one_character_too_long_are_rejected(make_ticket_data, overrides):
    with pytest.raises(ValidationError):
        make_ticket_data(**overrides)


def test_surrounding_whitespace_is_stripped(ticket_service, make_ticket_data):
    ticket = ticket_service.create_ticket(
        make_ticket_data(title="  VPN down  ", description="\tno access\n")
    )

    assert ticket.title == "VPN down"
    assert ticket.description == "no access"


def test_every_priority_and_category_is_accepted(make_ticket_data):
    for priority in TicketPriority:
        for category in TicketCategory:
            make_ticket_data(priority=priority, category=category)  # must not raise



@pytest.mark.parametrize(
    "bad_id",
    ["T 1", "T/1", "T-1\nFORGED", "T-1;DROP", "t\u00efcket"],
    ids=["space", "slash", "newline", "semicolon", "non-ascii"],
)
def test_ticket_ids_with_unsafe_characters_are_rejected(make_ticket_data, bad_id):
    with pytest.raises(ValidationError):
        make_ticket_data(bad_id)


def test_ticket_ids_may_use_letters_digits_dot_underscore_and_hyphen(make_ticket_data):
    assert make_ticket_data("Abc_1.2-Z").ticket_id == "Abc_1.2-Z"