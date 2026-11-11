"""The per-ticket pipeline: submit, dequeue, assign, handle failure.

No threads here. In Phase 4 worker threads simply call process_next() in a
loop, so the same logic is tested single-threaded first.
"""
from dataclasses import dataclass

from app.exceptions import QueueFullError
from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.services.engineer_service import EngineerService
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService


@dataclass(frozen=True)
class ProcessingResult:
    ticket_id: str
    success: bool
    error: str | None = None


class TicketProcessor:
    def __init__(
        self,
        ticket_service: TicketService,
        engineer_service: EngineerService,
        queue_service: QueueService,
    ) -> None:
        self._tickets = ticket_service
        self._engineers = engineer_service
        self._queue = queue_service

    def submit(self, ticket_id: str) -> Ticket:
        """Mark a ticket QUEUED and put its ID on the queue."""
        # update_status validates existence and the OPEN/FAILED -> QUEUED rule,
        # so an already-queued ticket can never be enqueued twice.
        ticket = self._tickets.update_status(ticket_id, TicketStatus.QUEUED)
        try:
            self._queue.enqueue(ticket_id)
        except QueueFullError:
            self._tickets.update_status(ticket_id, TicketStatus.FAILED)
            raise
        return ticket

    def process_ticket(self, ticket_id: str) -> Ticket:
        """Assign an engineer to one ticket. Raises on failure, leaving a
        consistent state (ticket FAILED, no engineer left reserved)."""
        # Raises before touching anything if the ticket is not QUEUED.
        self._tickets.update_status(ticket_id, TicketStatus.PROCESSING)
        engineer = None
        try:
            ticket = self._tickets.get_ticket(ticket_id)
            engineer = self._engineers.assign_engineer(ticket.category)
            return self._tickets.assign_engineer(ticket_id, engineer.engineer_id)
        except Exception:
            if engineer is not None:
                self._engineers.release_engineer(engineer.engineer_id)
            self._tickets.update_status(ticket_id, TicketStatus.FAILED)
            raise

    def process_next(self, timeout: float | None = None) -> ProcessingResult | None:
        """Process the ticket at the front of the queue.

        timeout=None never blocks; otherwise wait up to `timeout` seconds for
        a ticket to arrive. Returns None if nothing was available, otherwise
        a result. Never raises for a bad ticket, so one failure cannot stop
        the consumer.
        """
        if timeout is None:
            ticket_id = self._queue.dequeue_nowait()
        else:
            ticket_id = self._queue.dequeue(timeout)
        if ticket_id is None:
            return None
        try:
            self.process_ticket(ticket_id)
            return ProcessingResult(ticket_id, success=True)
        except Exception as exc:  # deliberate: the consumer must survive
            return ProcessingResult(ticket_id, success=False, error=str(exc))
        finally:
            # Exactly once per successful dequeue, success or failure.
            self._queue.task_done()