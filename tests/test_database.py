import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.database import (
    create_db_engine,
    init_db,
    make_session_factory,
    session_scope,
    sqlite_url,
)
from app.models.engineer import EngineerSkill
from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.models.ticket import Ticket
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService


def make_row(ticket_id: str) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        title="t",
        description="d",
        priority=TicketPriority.LOW,
        category=TicketCategory.OTHER,
        status=TicketStatus.OPEN,
        created_at=datetime.now(timezone.utc),
    )


def test_init_db_creates_the_tables_and_can_run_twice(engine):
    init_db(engine)  # second call must not fail

    tables = set(inspect(engine).get_table_names())
    assert {"tickets", "engineers", "engineer_skills"} <= tables


def test_database_itself_rejects_a_duplicate_ticket_id(session_factory):
    with session_factory() as session:
        session.add(make_row("T-1"))
        session.commit()

    with pytest.raises(IntegrityError):
        with session_factory() as session:
            session.add(make_row("T-1"))
            session.commit()


def test_database_enforces_the_engineer_foreign_key(session_factory):
    row = make_row("T-1")
    row.assigned_engineer_id = "ghost"  # no such engineer exists

    with pytest.raises(IntegrityError):
        with session_factory() as session:
            session.add(row)
            session.commit()


def test_database_rejects_a_status_outside_the_allowed_values(engine):
    insert = text(
        "INSERT INTO tickets (ticket_id, title, description, priority, category,"
        " status, created_at) VALUES ('T-1', 't', 'd', 'LOW', 'OTHER', 'BOGUS',"
        " '2026-01-01 00:00:00')"
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert)


def test_created_at_comes_back_as_timezone_aware_utc(ticket_service, make_ticket_data):
    ticket_service.create_ticket(make_ticket_data())

    fetched = ticket_service.get_ticket("T-1")  # a fresh read from the database

    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at.utcoffset() == timedelta(0)


def test_data_survives_a_restart(tmp_path, make_ticket_data):
    url = sqlite_url(tmp_path / "restart.db")

    first_run = create_db_engine(url)
    init_db(first_run)
    TicketService(make_session_factory(first_run)).create_ticket(make_ticket_data("T-1"))
    first_run.dispose()  # the "server" stops; only the file remains

    second_run = create_db_engine(url)  # a brand-new "server"
    try:
        found = TicketService(make_session_factory(second_run)).get_ticket("T-1")
        assert found.title == "VPN not connecting"
    finally:
        second_run.dispose()


def test_restore_queue_requeues_unfinished_tickets_in_creation_order(
    processor, ticket_service, engineer_service, make_ticket_data
):
    for ticket_id in ("T-1", "T-2", "T-3"):
        ticket_service.create_ticket(make_ticket_data(ticket_id))
    processor.submit("T-1")
    processor.submit("T-2")
    # A worker was in the middle of T-1 when the "server" died:
    ticket_service.update_status("T-1", TicketStatus.PROCESSING)

    # "Restart": a brand-new, empty in-memory queue over the same database.
    fresh_queue = QueueService()
    fresh_processor = TicketProcessor(ticket_service, engineer_service, fresh_queue)

    assert fresh_processor.restore_queue() == 2
    assert [fresh_queue.dequeue_nowait(), fresh_queue.dequeue_nowait()] == ["T-1", "T-2"]
    assert ticket_service.get_ticket("T-1").status == TicketStatus.QUEUED
    assert ticket_service.get_ticket("T-3").status == TicketStatus.OPEN  # never submitted

def test_init_db_refuses_a_database_with_an_outdated_schema(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE tickets (id INTEGER PRIMARY KEY, title TEXT)")
    connection.commit()
    connection.close()

    engine = create_db_engine(sqlite_url(path))
    try:
        with pytest.raises(RuntimeError, match="missing columns"):
            init_db(engine)
    finally:
        engine.dispose()


def test_session_scope_rolls_back_when_the_body_raises(session_factory):
    with pytest.raises(RuntimeError):
        with session_scope(session_factory) as session:
            session.add(make_row("T-1"))
            session.flush()  # the INSERT is sent, but not committed
            raise RuntimeError("boom")

    with session_factory() as session:
        assert session.scalars(select(Ticket)).all() == []


def test_session_scope_given_a_session_leaves_committing_to_the_caller(session_factory):
    with session_factory() as outer:
        with session_scope(session_factory, outer) as session:
            assert session is outer
            session.add(make_row("T-1"))
        outer.rollback()  # the scope did not commit, so we can still undo it all

    with session_factory() as session:
        assert session.scalars(select(Ticket)).all() == []


def test_a_naive_datetime_is_rejected(session_factory):
    row = make_row("T-1")
    row.created_at = datetime(2026, 1, 1, 12, 0, 0)  # no timezone

    with pytest.raises((ValueError, StatementError), match="Naive datetime"):
        with session_factory() as session:
            session.add(row)
            session.commit()


def test_each_skill_is_stored_as_its_own_row(
    engineer_service, session_factory, make_engineer_data
):
    engineer_service.add_engineer(
        make_engineer_data(skills={TicketCategory.NETWORK, TicketCategory.ACCESS})
    )

    with session_factory() as session:
        count = session.scalar(select(func.count()).select_from(EngineerSkill))

    assert count == 2


def test_sqlite_url_is_portable(tmp_path):
    url = sqlite_url(tmp_path / "x.db")

    assert url.startswith("sqlite:///")
    assert url.endswith("/x.db")
    assert "\\" not in url



def test_created_at_defaults_to_now_when_not_given(session_factory):
    row = Ticket(
        ticket_id="T-1", title="t", description="d",
        priority=TicketPriority.LOW, category=TicketCategory.OTHER,
        status=TicketStatus.OPEN,
    )  # note: no created_at
    with session_factory() as session:
        session.add(row)
        session.commit()

    with session_factory() as session:
        fetched = session.scalars(select(Ticket)).one()

    assert abs(datetime.now(timezone.utc) - fetched.created_at) < timedelta(minutes=1)



def test_database_error_messages_do_not_contain_row_values(session_factory):
    first = make_row("T-1")
    first.title = "SECRET-TITLE"
    with session_factory() as session:
        session.add(first)
        session.commit()

    duplicate = make_row("T-1")
    duplicate.title = "SECRET-TITLE"
    with pytest.raises(IntegrityError) as caught:
        with session_factory() as session:
            session.add(duplicate)
            session.commit()

    # hide_parameters=True keeps bound values out of the message, and so out of logs.
    assert "SECRET-TITLE" not in str(caught.value)