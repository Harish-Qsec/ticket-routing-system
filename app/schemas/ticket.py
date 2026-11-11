"""Pydantic schemas that validate ticket input."""
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TicketCategory, TicketPriority, TicketStatus


class TicketCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ticket_id: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    priority: TicketPriority
    category: TicketCategory


class TicketStatusUpdate(BaseModel):
    status: TicketStatus