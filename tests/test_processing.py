import pytest

from app.exceptions import (
    InvalidStatusTransitionError,
    QueueFullError,
    TicketNotFoundError,
)
from app.models.enums import TicketStatus
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from tests.helpers import joins_within


def test_submit_marks_ticket_queued_and_enqueues(
    processor, ticket_service, queue_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())

    processor.submit("T-1")

    assert ticket_service.get_ticket("T-1").status == TicketStatus.QUEUED
    assert queue_service.size() == 1


def test_submit_unknown_ticket_raises(processor, queue_service):
    with pytest.raises(TicketNotFoundError):
        processor.submit("nope")

    assert queue_service.is_empty()


def test_submit_twice_is_rejected_and_not_duplicated(
    processor, ticket_service, queue_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    with pytest.raises(InvalidStatusTransitionError):
        processor.submit("T-1")

    assert queue_service.size() == 1


def test_submit_to_full_queue_marks_ticket_failed(
    ticket_service, engineer_service, make_ticket_data
):
    small_queue = QueueService(maxsize=1)
    processor = TicketProcessor(ticket_service, engineer_service, small_queue)
    ticket_service.create_ticket(make_ticket_data("T-1"))
    ticket_service.create_ticket(make_ticket_data("T-2"))
    processor.submit("T-1")

    with pytest.raises(QueueFullError):
        processor.submit("T-2")

    assert ticket_service.get_ticket("T-2").status == TicketStatus.FAILED
    assert small_queue.size() == 1


def test_process_next_on_empty_queue_returns_none(processor):
    assert processor.process_next() is None


def test_process_next_assigns_engineer_and_updates_ticket(
    processor, ticket_service, engineer_service, make_ticket_data, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    result = processor.process_next()

    assert result.success is True
    assert result.ticket_id == "T-1"
    assert result.error is None
    ticket = ticket_service.get_ticket("T-1")
    assert ticket.status == TicketStatus.ASSIGNED
    assert ticket.assigned_engineer_id == "E-1"
    assert engineer_service.get_engineer("E-1").is_available is False


def test_tickets_are_processed_in_fifo_order(
    processor, ticket_service, engineer_service, queue_service,
    make_ticket_data, make_engineer_data,
):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    engineer_service.add_engineer(make_engineer_data("E-2"))
    for ticket_id in ("T-1", "T-2", "T-3"):
        ticket_service.create_ticket(make_ticket_data(ticket_id))
        processor.submit(ticket_id)

    results = [processor.process_next() for _ in range(2)]

    assert [r.ticket_id for r in results] == ["T-1", "T-2"]
    assert ticket_service.get_ticket("T-1").assigned_engineer_id == "E-1"
    assert ticket_service.get_ticket("T-2").assigned_engineer_id == "E-2"
    assert ticket_service.get_ticket("T-3").status == TicketStatus.QUEUED
    assert queue_service.size() == 1


def test_no_available_engineer_marks_ticket_failed_without_crashing(
    processor, ticket_service, queue_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    result = processor.process_next()

    assert result.success is False
    assert "No available engineer" in result.error
    ticket = ticket_service.get_ticket("T-1")
    assert ticket.status == TicketStatus.FAILED
    assert ticket.assigned_engineer_id is None
    assert queue_service.is_empty()


def test_failed_ticket_can_be_resubmitted_and_then_succeeds(
    processor, ticket_service, engineer_service, make_ticket_data, make_engineer_data
):
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")
    assert processor.process_next().success is False  # nobody to assign

    engineer_service.add_engineer(make_engineer_data("E-1"))
    processor.submit("T-1")  # FAILED -> QUEUED is allowed
    result = processor.process_next()

    assert result.success is True
    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED


def test_queue_join_completes_even_when_processing_fails(
    processor, ticket_service, queue_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")
    processor.process_next()  # fails: no engineers

    assert joins_within(queue_service)


def test_unexpected_error_is_contained_and_ticket_marked_failed(
    processor, ticket_service, engineer_service, make_ticket_data
):
    def explode(category, **kwargs):
        raise RuntimeError("disk on fire")

    engineer_service.assign_engineer = explode
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    result = processor.process_next()

    assert result.success is False
    assert "disk on fire" in result.error
    assert ticket_service.get_ticket("T-1").status == TicketStatus.FAILED


def test_engineer_reservation_is_rolled_back_if_recording_the_assignment_fails(
    processor, ticket_service, engineer_service, make_ticket_data, make_engineer_data
):
    def explode(ticket_id, engineer_id, **kwargs):
        raise RuntimeError("db write failed")

    engineer_service.add_engineer(make_engineer_data("E-1"))
    ticket_service.assign_engineer = explode
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    result = processor.process_next()

    assert result.success is False
    assert engineer_service.get_engineer("E-1").is_available is True
    assert ticket_service.get_ticket("T-1").status == TicketStatus.FAILED


def test_duplicate_queue_entry_is_processed_only_once(
    processor, ticket_service, engineer_service, queue_service,
    make_ticket_data, make_engineer_data,
):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    engineer_service.add_engineer(make_engineer_data("E-2"))
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")
    queue_service.enqueue("T-1")  # sneak in a duplicate entry

    first = processor.process_next()
    second = processor.process_next()

    assert first.success is True
    assert second.success is False
    ticket = ticket_service.get_ticket("T-1")
    assert ticket.status == TicketStatus.ASSIGNED
    assert ticket.assigned_engineer_id == "E-1"
    assert engineer_service.get_engineer("E-2").is_available is True