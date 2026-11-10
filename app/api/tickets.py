from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket
from app.schemas import TicketCreate, TicketRead
from app.services.queue import TicketQueue

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    request: Request,
    session: Session = Depends(get_db),
) -> Ticket:
    ticket = Ticket(subject=payload.subject, description=payload.description)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    queue: TicketQueue = request.app.state.ticket_queue
    await queue.put(ticket.id)
    return ticket


@router.get("", response_model=list[TicketRead])
def list_tickets(session: Session = Depends(get_db)) -> list[Ticket]:
    return list(session.scalars(select(Ticket).order_by(Ticket.id.desc())))