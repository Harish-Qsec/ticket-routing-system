import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import Ticket
from app.services.queue import TicketQueue

logger = logging.getLogger(__name__)


async def run_worker(worker_id: int, queue: TicketQueue, session_factory: Callable[[], Session]) -> None:
    worker_name = f"worker-{worker_id}"
    while True:
        ticket_id = await queue.get()
        try:
            with session_factory() as session:
                ticket = session.get(Ticket, ticket_id)
                if ticket is not None and ticket.status == "queued":
                    ticket.status = "routed"
                    ticket.assigned_worker = worker_name
                    session.commit()
        except Exception:
            logger.exception("Failed to route ticket %s", ticket_id)
        finally:
            queue.task_done()