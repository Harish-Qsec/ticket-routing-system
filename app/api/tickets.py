"""Ticket endpoints. HTTP concerns only; the logic lives in the services."""
from fastapi import APIRouter, Response, status

from app.api.dependencies import ProcessorDep, TicketServiceDep
from app.schemas.ticket import TicketCreate, TicketRead, TicketStatusUpdate

router = APIRouter(prefix="/tickets", tags=["tickets"])


# These are plain "def" functions on purpose: they do blocking database work,
# so FastAPI runs each call in a worker thread instead of freezing its event loop.


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(data: TicketCreate, response: Response, tickets: TicketServiceDep):
    ticket = tickets.create_ticket(data)
    response.headers["Location"] = f"/tickets/{ticket.ticket_id}"
    return ticket


@router.get("", response_model=list[TicketRead])
def list_tickets(tickets: TicketServiceDep):
    return tickets.list_tickets()


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: str, tickets: TicketServiceDep):
    return tickets.get_ticket(ticket_id)


@router.put("/{ticket_id}/status", response_model=TicketRead)
def update_ticket_status(
    ticket_id: str, body: TicketStatusUpdate, processor: ProcessorDep
):
    # TicketStatusUpdate only lets RESOLVED through, so resolving (which also
    # frees the engineer) is the one status change a client can request.
    return processor.resolve_ticket(ticket_id)


@router.post(
    "/{ticket_id}/process",
    response_model=TicketRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def process_ticket(ticket_id: str, processor: ProcessorDep):
    # 202 Accepted: the ticket is queued; a worker thread handles it later.
    return processor.submit(ticket_id)