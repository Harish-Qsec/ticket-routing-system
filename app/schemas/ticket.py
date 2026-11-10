from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)


class TicketRead(BaseModel):
    id: int
    subject: str
    description: str
    status: str
    assigned_worker: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)