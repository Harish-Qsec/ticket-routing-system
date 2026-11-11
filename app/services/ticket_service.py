"""Ticket management.

Storage is an in-memory dict for now. In Phase 5 the dict is replaced by
SQLAlchemy queries; the public method names stay the same.

Thread safety: API threads and worker threads share one TicketService, and
several methods are "check, then change" sequences. One lock makes each
public method atomic with respect to the others.
"""
import threading

from app.exceptions import (
    DuplicateTicketError,
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


class TicketService:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    # Private helpers: the caller must already hold self._lock.

    def _get(self, ticket_id: str) -> Ticket:
        try:
            return self._tickets[ticket_id]
        except KeyError:
            raise TicketNotFoundError(ticket_id) from None

    @staticmethod
    def _check_transition(ticket: Ticket, new_status: TicketStatus) -> None:
        if new_status not in ALLOWED_TRANSITIONS[ticket.status]:
            raise InvalidStatusTransitionError(ticket.status, new_status)

    # Public API: each method takes the lock exactly once.

    def create_ticket(self, data: TicketCreate) -> Ticket:
        with self._lock:
            if data.ticket_id in self._tickets:
                raise DuplicateTicketError(data.ticket_id)
            ticket = Ticket(
                ticket_id=data.ticket_id,
                title=data.title,
                description=data.description,
                priority=data.priority,
                category=data.category,
            )
            self._tickets[ticket.ticket_id] = ticket
            return ticket

    def get_ticket(self, ticket_id: str) -> Ticket:
        with self._lock:
            return self._get(ticket_id)

    def list_tickets(self) -> list[Ticket]:
        with self._lock:
            return list(self._tickets.values())

    def update_status(self, ticket_id: str, new_status: TicketStatus) -> Ticket:
        with self._lock:
            ticket = self._get(ticket_id)
            self._check_transition(ticket, new_status)
            ticket.status = new_status
            return ticket

    def assign_engineer(self, ticket_id: str, engineer_id: str) -> Ticket:
        """Record the chosen engineer on a ticket and mark it ASSIGNED."""
        with self._lock:
            ticket = self._get(ticket_id)
            self._check_transition(ticket, TicketStatus.ASSIGNED)
            ticket.assigned_engineer_id = engineer_id
            ticket.status = TicketStatus.ASSIGNED
            return ticket