"""Phase 3 demo: FIFO processing, one ticket at a time (no threads yet)."""
from app.models.enums import TicketCategory, TicketPriority
from app.schemas.engineer import EngineerCreate
from app.schemas.ticket import TicketCreate
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService


def main() -> None:
    tickets = TicketService()
    engineers = EngineerService()
    queue = QueueService()
    processor = TicketProcessor(tickets, engineers, queue)

    for engineer_id, name in (("E-1", "Asha"), ("E-2", "Ravi")):
        engineers.add_engineer(
            EngineerCreate(
                engineer_id=engineer_id, name=name, skills={TicketCategory.NETWORK}
            )
        )

    for n in range(1, 5):
        ticket_id = f"T-{n}"
        tickets.create_ticket(
            TicketCreate(
                ticket_id=ticket_id,
                title=f"Network issue {n}",
                description="Demo ticket",
                priority=TicketPriority.MEDIUM,
                category=TicketCategory.NETWORK,
            )
        )
        processor.submit(ticket_id)
    print(f"Submitted 4 tickets, queue size = {queue.size()}")

    while (result := processor.process_next()) is not None:
        ticket = tickets.get_ticket(result.ticket_id)
        print(
            f"{result.ticket_id}: success={result.success} status={ticket.status} "
            f"engineer={ticket.assigned_engineer_id} error={result.error}"
        )
    print("Queue is empty, so process_next() returned None")

    queue.join()
    print("queue.join() returned: every dequeued ticket was marked task_done")

    # Recovery: free an engineer and retry a failed ticket.
    engineers.release_engineer("E-1")
    processor.submit("T-3")
    result = processor.process_next()
    ticket = tickets.get_ticket("T-3")
    print(f"Retry T-3: success={result.success} status={ticket.status} "
          f"engineer={ticket.assigned_engineer_id}")


if __name__ == "__main__":
    main()