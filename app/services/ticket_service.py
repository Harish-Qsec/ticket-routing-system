"""Ticket management, persisted with SQLAlchemy.

Concurrency is handled by the database, not by Python locks:
  * duplicate IDs are rejected by a UNIQUE constraint;
  * status changes are one conditional UPDATE ("compare-and-set"), so two
    threads can never both move the same ticket through the same transition.
"""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.exceptions import (
    DuplicateTicketError,
    EngineerNotFoundError,
    InvalidStatusTransitionError,
    TicketNotFoundError,
)
from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate

# Which status changes are legal. Anything not listed is rejected.
ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.OPEN: frozenset({TicketStatus.QUEUED}),
    TicketStatus.QUEUED: frozenset({TicketStatus.PROCESSING, TicketStatus.FAILED}),
    TicketStatus.PROCESSING: frozenset({TicketStatus.ASSIGNED, TicketStatus.FAILED}),
    TicketStatus.ASSIGNED: frozenset({TicketStatus.RESOLVED}),
    TicketStatus.FAILED: frozenset({TicketStatus.QUEUED}),
    TicketStatus.RESOLVED: frozenset(),
}

# The same table turned around: "to reach X, the ticket must currently be in..."
_ALLOWED_FROM: dict[TicketStatus, list[TicketStatus]] = {
    target: [src for src, targets in ALLOWED_TRANSITIONS.items() if target in targets]
    for target in TicketStatus
}


class TicketService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self._session_factory

    @staticmethod
    def _get(session: Session, ticket_id: str) -> Ticket:
        # populate_existing: always show what the database says right now,
        # even if this session loaded the row earlier.
        ticket = session.scalars(
            select(Ticket)
            .where(Ticket.ticket_id == ticket_id)
            .execution_options(populate_existing=True)
        ).first()
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        return ticket

    @staticmethod
    def _transition(
        session: Session, ticket_id: str, new_status: TicketStatus, **extra_values
    ) -> None:
        """Atomic compare-and-set: change the status only if the current
        status allows it, in a single UPDATE statement."""
        result = session.execute(
            update(Ticket)
            .where(
                Ticket.ticket_id == ticket_id,
                Ticket.status.in_(_ALLOWED_FROM[new_status]),
            )
            .values(status=new_status, **extra_values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            return
        # Nothing changed: find out why, so we can raise the right error.
        current = session.scalar(
            select(Ticket.status).where(Ticket.ticket_id == ticket_id)
        )
        if current is None:
            raise TicketNotFoundError(ticket_id)
        raise InvalidStatusTransitionError(current, new_status)

    def create_ticket(self, data: TicketCreate) -> Ticket:
        with session_scope(self._session_factory) as session:
            ticket = Ticket(
                ticket_id=data.ticket_id,
                title=data.title,
                description=data.description,
                priority=data.priority,
                category=data.category,
                status=TicketStatus.OPEN,
                created_at=datetime.now(timezone.utc),
            )
            session.add(ticket)
            try:
                session.flush()  # sends the INSERT now, so a duplicate fails here
            except IntegrityError:
                raise DuplicateTicketError(data.ticket_id) from None
            return ticket

    def get_ticket(self, ticket_id: str, *, session: Session | None = None) -> Ticket:
        with session_scope(self._session_factory, session) as active:
            return self._get(active, ticket_id)

    def list_tickets(self) -> list[Ticket]:
        with session_scope(self._session_factory) as session:
            return list(session.scalars(select(Ticket).order_by(Ticket.id)))

    def update_status(self, ticket_id: str, new_status: TicketStatus, *, session: Session | None = None) -> Ticket:
        with session_scope(self._session_factory, session) as active:
            self._transition(active, ticket_id, new_status)
            return self._get(active, ticket_id)

    def assign_engineer(
        self, ticket_id: str, engineer_id: str, *, session: Session | None = None
    ) -> Ticket:
        """Record the chosen engineer on a ticket and mark it ASSIGNED."""
        with session_scope(self._session_factory, session) as active:
            try:
                self._transition(
                    active, ticket_id, TicketStatus.ASSIGNED,
                    assigned_engineer_id=engineer_id,
                )
            except IntegrityError:  # the foreign key found no such engineer
                raise EngineerNotFoundError(engineer_id) from None
            return self._get(active, ticket_id)

    def requeue_interrupted(self) -> list[str]:
        """Startup recovery.

        A ticket still PROCESSING after a restart was cut off mid-work. Its
        engineer reservation was never committed (assignment is atomic), so
        it is safe to put it back to QUEUED. Returns the IDs of every QUEUED
        ticket in creation order, ready to be re-enqueued.
        """
        with session_scope(self._session_factory) as session:
            session.execute(
                update(Ticket)
                .where(Ticket.status == TicketStatus.PROCESSING)
                .values(status=TicketStatus.QUEUED)
                .execution_options(synchronize_session=False)
            )
            return list(
                session.scalars(
                    select(Ticket.ticket_id)
                    .where(Ticket.status == TicketStatus.QUEUED)
                    .order_by(Ticket.id)
                )
            )