import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy import select

from app.api import health, tickets
from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Ticket
from app.services.queue import TicketQueue
from app.services.workers import run_worker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    queue = TicketQueue()
    app.state.ticket_queue = queue
    workers = [
        asyncio.create_task(run_worker(worker_id, queue, SessionLocal))
        for worker_id in range(1, settings.worker_count + 1)
    ]
    with SessionLocal() as session:
        pending_ids = session.scalars(select(Ticket.id).where(Ticket.status == "queued"))
        for ticket_id in pending_ids:
            queue.put_nowait(ticket_id)
    try:
        yield
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


app = FastAPI(title="Ticket Routing System", lifespan=lifespan)
app.include_router(health.router)
app.include_router(tickets.router)