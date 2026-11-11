"""Engineer domain model."""
from dataclasses import dataclass

from app.models.enums import TicketCategory


@dataclass
class Engineer:
    engineer_id: str
    name: str
    skills: set[TicketCategory]
    is_available: bool = True