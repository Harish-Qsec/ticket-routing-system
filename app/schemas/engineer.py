"""Pydantic schemas that validate engineer input."""
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TicketCategory


class EngineerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    engineer_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    skills: set[TicketCategory] = Field(min_length=1)
    is_available: bool = True