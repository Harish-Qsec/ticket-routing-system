"""Builds the object graph once, at application startup."""
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.config import Settings
from app.database import create_db_engine, init_db, make_session_factory
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService
from app.services.worker_service import WorkerPool


@dataclass
class AppContainer:
    settings: Settings
    engine: Engine
    tickets: TicketService
    engineers: EngineerService
    queue: QueueService
    processor: TicketProcessor
    pool: WorkerPool


def build_container(settings: Settings) -> AppContainer:
    engine = create_db_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    tickets = TicketService(session_factory)
    engineers = EngineerService(session_factory)
    queue = QueueService(maxsize=settings.queue_maxsize)
    processor = TicketProcessor(tickets, engineers, queue)
    pool = WorkerPool(
        processor,
        queue,
        num_workers=settings.num_workers,
        poll_timeout=settings.poll_timeout,
    )
    return AppContainer(settings, engine, tickets, engineers, queue, processor, pool)