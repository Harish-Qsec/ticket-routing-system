"""Ticket table."""
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, enum_type
from app.models.enums import TicketCategory, TicketPriority, TicketStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Ticket(Base):
    __tablename__ = "tickets"

    # Surrogate key: gives a reliable creation order. ticket_id is the
    # business key the outside world uses, and it must be unique.
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[TicketPriority] = mapped_column(enum_type(TicketPriority))
    category: Mapped[TicketCategory] = mapped_column(enum_type(TicketCategory))
    status: Mapped[TicketStatus] = mapped_column(
        enum_type(TicketStatus), default=TicketStatus.OPEN, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utc_now)
    assigned_engineer_id: Mapped[str | None] = mapped_column(
        ForeignKey("engineers.engineer_id"), default=None
    )