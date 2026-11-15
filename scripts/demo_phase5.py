"""Phase 5 demo: data survives a simulated crash, and the queue is rebuilt.

Usage (from the project root):
    python -m scripts.demo_phase5
Creates demo_phase5.db in the current folder (ignored by git).
"""
from pathlib import Path

from app.database import create_db_engine, init_db, make_session_factory, sqlite_url
from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.schemas.engineer import EngineerCreate
from app.schemas.ticket import TicketCreate
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService
from app.services.worker_service import WorkerPool

DB_FILE = Path("demo_phase5.db")


def build(engine):
    session_factory = make_session_factory(engine)
    tickets = TicketService(session_factory)
    engineers = EngineerService(session_factory)
    queue = QueueService()
    return tickets, engineers, queue, TicketProcessor(tickets, engineers, queue)


def show(tickets, label):
    summary = ", ".join(f"{t.ticket_id}={t.status}" for t in tickets.list_tickets())
    print(f"{label}: {summary}")


def main() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{DB_FILE}{suffix}").unlink(missing_ok=True)

    # ---------- first "server run" ----------
    engine = create_db_engine(sqlite_url(DB_FILE))
    init_db(engine)
    tickets, engineers, queue, processor = build(engine)
    for n in range(1, 5):
        engineers.add_engineer(
            EngineerCreate(
                engineer_id=f"E-{n}", name=f"Engineer {n}",
                skills={TicketCategory.NETWORK},
            )
        )
        tickets.create_ticket(
            TicketCreate(
                ticket_id=f"T-{n}", title=f"Network issue {n}",
                description="Demo ticket", priority=TicketPriority.MEDIUM,
                category=TicketCategory.NETWORK,
            )
        )
        processor.submit(f"T-{n}")
    print(f"Run 1: 4 tickets submitted, queue size = {queue.size()}")

    processor.process_next()  # T-1 is fully processed
    tickets.update_status("T-2", TicketStatus.PROCESSING)  # T-2 is mid-flight...
    show(tickets, "Run 1, just before the crash")

    engine.dispose()
    del queue, processor  # ...and the in-memory queue is lost
    print("--- simulated crash: the in-memory queue is gone ---")

    # ---------- second "server run" ----------
    engine = create_db_engine(sqlite_url(DB_FILE))
    tickets, engineers, queue, processor = build(engine)
    print(f"Run 2: new process, queue size = {queue.size()}")
    show(tickets, "Run 2, data read back from the file")

    restored = processor.restore_queue()
    print(f"Run 2: restore_queue() put {restored} unfinished tickets back on the queue")

    pool = WorkerPool(processor, queue, num_workers=3)
    pool.start()
    pool.stop(drain=True, timeout=30.0)
    show(tickets, "Run 2, after the workers finished")

    assigned = [t.assigned_engineer_id for t in tickets.list_tickets()]
    print(f"engineers used: {len(set(assigned))} distinct out of {len(assigned)} tickets")
    engine.dispose()


if __name__ == "__main__":
    main()