"""Pydantic schemas for engineers: what clients send and what the API returns."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TicketCategory


class EngineerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    engineer_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    skills: set[TicketCategory] = Field(min_length=1)
    is_available: bool = True


class EngineerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engineer_id: str
    name: str
    skills: list[TicketCategory]
    is_available: bool

    @field_validator("skills")
    @classmethod
    def sort_skills(cls, value: list[TicketCategory]) -> list[TicketCategory]:
        # The ORM gives us a set (no order); sort so responses are stable.
        return sorted(value)