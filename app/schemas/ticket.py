"""Pydantic schemas for tickets: what clients send and what the API returns."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TicketCategory, TicketPriority, TicketStatus

# Statuses a client may ask for. Everything else belongs to the pipeline:
# QUEUED/FAILED are set through POST /tickets/{id}/process, and
# PROCESSING/ASSIGNED are set by the worker threads.
CLIENT_SETTABLE_STATUSES = frozenset({TicketStatus.RESOLVED})


class TicketCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ticket_id: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    priority: TicketPriority
    category: TicketCategory


class TicketStatusUpdate(BaseModel):
    status: TicketStatus

    @field_validator("status")
    @classmethod
    def status_must_be_client_settable(cls, value: TicketStatus) -> TicketStatus:
        if value not in CLIENT_SETTABLE_STATUSES:
            allowed = ", ".join(sorted(CLIENT_SETTABLE_STATUSES))
            raise ValueError(
                f"status must be one of: {allowed} "
                "(other statuses are managed by the system)"
            )
        return value


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # build it from an ORM object

    ticket_id: str
    title: str
    description: str
    priority: TicketPriority
    category: TicketCategory
    status: TicketStatus
    created_at: datetime
    assigned_engineer_id: str | None