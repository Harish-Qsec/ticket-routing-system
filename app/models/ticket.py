"""Ticket domain model."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.enums import TicketCategory, TicketPriority, TicketStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Ticket:
    ticket_id: str
    title: str
    description: str
    priority: TicketPriority
    category: TicketCategory
    status: TicketStatus = TicketStatus.OPEN
    created_at: datetime = field(default_factory=_utc_now)
    assigned_engineer_id: str | None = None