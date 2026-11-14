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
        if ticket_service.session_factory is not engineer_service.session_factory:
            raise ValueError(
                "TicketService and EngineerService must share one session factory "
                "so that an assignment can be a single database transaction"
            )
        self._tickets = ticket_service
        self._engineers = engineer_service
        self._queue = queue_service
        self._session_factory = ticket_service.session_factory

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
        """Assign an engineer to one ticket.

        Reserving the engineer and recording the assignment happen in ONE
        database transaction: either both are saved or neither is. On any
        failure the ticket is marked FAILED and the error is re-raised.
        """
        # Raises before touching anything if the ticket is not QUEUED.
        self._tickets.update_status(ticket_id, TicketStatus.PROCESSING)
        try:
            with self._session_factory() as session:
                ticket = self._tickets.get_ticket(ticket_id, session=session)
                engineer = self._engineers.assign_engineer(
                    ticket.category, session=session
                )
                assigned = self._tickets.assign_engineer(
                    ticket_id, engineer.engineer_id, session=session
                )
                session.commit()  # the single commit point
            return assigned
        except Exception:
            # Leaving the "with" block without committing rolled everything
            # back, so no engineer stays reserved.
            self._tickets.update_status(ticket_id, TicketStatus.FAILED)
            raise

    def restore_queue(self) -> int:
        """Startup recovery: rebuild the in-memory queue from the database.

        Returns how many tickets were put back on the queue. Order is
        creation order, which approximates (but is not guaranteed to equal)
        the original submission order.
        """
        ticket_ids = self._tickets.requeue_interrupted()
        for ticket_id in ticket_ids:
            self._queue.enqueue(ticket_id)
        return len(ticket_ids)

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