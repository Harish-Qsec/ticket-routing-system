import logging

import pytest

from app.exceptions import QueueFullError
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService

SECRET_TITLE = "SECRET-TITLE-9f3a"
SECRET_DESCRIPTION = "SECRET-DESCRIPTION-7c1e"
SECRET_NAME = "SECRET-NAME-4d2b"


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    return caplog


def messages(logs, logger_name, level=None):
    return [
        r.getMessage()
        for r in logs.records
        if r.name == logger_name and (level is None or r.levelno == level)
    ]


def test_creating_a_ticket_is_logged_without_its_text(logs, ticket_service, make_ticket_data):
    ticket_service.create_ticket(
        make_ticket_data(title=SECRET_TITLE, description=SECRET_DESCRIPTION)
    )

    created = messages(logs, "app.services.ticket_service", logging.INFO)
    assert any("ticket created" in m and "ticket_id=T-1" in m for m in created)
    assert SECRET_TITLE not in logs.text
    assert SECRET_DESCRIPTION not in logs.text


def test_adding_an_engineer_is_logged_without_the_name(
    logs, engineer_service, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1", name=SECRET_NAME))

    added = messages(logs, "app.services.engineer_service", logging.INFO)
    assert any("engineer added" in m and "engineer_id=E-1" in m for m in added)
    assert SECRET_NAME not in logs.text


def test_queueing_a_ticket_is_logged(logs, processor, ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())

    processor.submit("T-1")

    queued = messages(logs, "app.services.processing_service", logging.INFO)
    assert any(
        "ticket queued" in m and "ticket_id=T-1" in m and "queue_size=1" in m
        for m in queued
    )


def test_assigning_an_engineer_is_logged(
    logs, processor, ticket_service, engineer_service, make_ticket_data, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    processor.process_next()

    assigned = messages(logs, "app.services.processing_service", logging.INFO)
    assert any(
        "ticket assigned" in m and "ticket_id=T-1" in m and "engineer_id=E-1" in m
        for m in assigned
    )


def test_a_failed_assignment_is_logged_as_a_warning(
    logs, processor, ticket_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    processor.process_next()  # no engineers exist

    failed = messages(logs, "app.services.processing_service", logging.WARNING)
    assert any("ticket_id=T-1" in m and "No available engineer" in m for m in failed)


def test_an_unexpected_processing_error_is_logged_with_a_traceback(
    logs, processor, ticket_service, engineer_service, make_ticket_data
):
    def explode(category, **kwargs):
        raise RuntimeError("disk on fire")

    engineer_service.assign_engineer = explode
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")

    processor.process_next()

    crashes = [
        r for r in logs.records
        if r.name == "app.services.processing_service" and r.levelno == logging.ERROR
    ]
    assert crashes
    assert crashes[0].exc_info is not None
    assert "ticket_id=T-1" in crashes[0].getMessage()


def test_a_full_queue_is_logged_as_a_warning(
    logs, ticket_service, engineer_service, make_ticket_data
):
    small_processor = TicketProcessor(ticket_service, engineer_service, QueueService(maxsize=1))
    ticket_service.create_ticket(make_ticket_data("T-1"))
    ticket_service.create_ticket(make_ticket_data("T-2"))
    small_processor.submit("T-1")

    with pytest.raises(QueueFullError):
        small_processor.submit("T-2")

    warnings = messages(logs, "app.services.processing_service", logging.WARNING)
    assert any("queue is full" in m and "ticket_id=T-2" in m for m in warnings)


def test_resolving_a_ticket_is_logged(
    logs, processor, ticket_service, engineer_service, make_ticket_data, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")
    processor.process_next()

    processor.resolve_ticket("T-1")

    resolved = messages(logs, "app.services.processing_service", logging.INFO)
    assert any(
        "ticket resolved" in m and "ticket_id=T-1" in m and "engineer_released=True" in m
        for m in resolved
    )


def test_restoring_the_queue_is_logged(
    logs, processor, ticket_service, engineer_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    processor.submit("T-1")
    fresh_processor = TicketProcessor(ticket_service, engineer_service, QueueService())

    fresh_processor.restore_queue()

    restored = messages(logs, "app.services.processing_service", logging.INFO)
    assert any("queue restored" in m and "1 ticket" in m for m in restored)