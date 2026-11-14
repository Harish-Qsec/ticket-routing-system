"""Phase 4 demo: real worker threads and out-of-order completion.

Usage (from the project root):
    python -m scripts.demo_phase4
    python -m scripts.demo_phase4 --workers 1 --tickets 8
"""
import argparse
import logging
import random
import time

from app.models.enums import TicketCategory, TicketPriority
from app.schemas.engineer import EngineerCreate
from app.schemas.ticket import TicketCreate
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService
from app.services.worker_service import WorkerPool


class SlowProcessor(TicketProcessor):
    """Pretends every ticket takes a random amount of time to process."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started: list[str] = []
        self.finished: list[str] = []

    def process_ticket(self, ticket_id: str):
        self.started.append(ticket_id)  # list.append is atomic in CPython
        time.sleep(random.uniform(0.01, 0.15))
        ticket = super().process_ticket(ticket_id)
        self.finished.append(ticket_id)
        return ticket


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--tickets", type=int, default=8)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(threadName)-9s %(message)s",
        datefmt="%H:%M:%S",
    )

    tickets = TicketService()
    engineers = EngineerService()
    queue = QueueService()
    processor = SlowProcessor(tickets, engineers, queue)

    for n in range(1, args.tickets + 1):
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

    pool = WorkerPool(processor, queue, num_workers=args.workers)
    began = time.perf_counter()
    pool.start()
    clean = pool.stop(drain=True, timeout=30.0)
    elapsed = time.perf_counter() - began

    print(f"\nclean shutdown: {clean}  (elapsed {elapsed:.2f}s, {args.workers} worker(s))")
    print("start order :", processor.started)
    print("finish order:", processor.finished)
    print("same order  :", processor.started == processor.finished)
    all_tickets = tickets.list_tickets()
    assigned = [t for t in all_tickets if t.status == "ASSIGNED"]
    distinct = {t.assigned_engineer_id for t in assigned}
    print(f"assigned    : {len(assigned)}/{len(all_tickets)} tickets, "
          f"{len(distinct)} distinct engineers")


if __name__ == "__main__":
    main()