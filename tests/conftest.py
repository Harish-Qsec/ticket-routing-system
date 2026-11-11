"""Shared fixtures. Each test gets fresh, empty services (no shared state)."""
import pytest

from app.models.enums import TicketCategory, TicketPriority
from app.schemas.engineer import EngineerCreate
from app.schemas.ticket import TicketCreate
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService


@pytest.fixture
def ticket_service() -> TicketService:
    return TicketService()


@pytest.fixture
def engineer_service() -> EngineerService:
    return EngineerService()


@pytest.fixture
def queue_service() -> QueueService:
    return QueueService()


@pytest.fixture
def processor(ticket_service, engineer_service, queue_service) -> TicketProcessor:
    return TicketProcessor(ticket_service, engineer_service, queue_service)


@pytest.fixture
def make_ticket_data():
    """Factory: build valid ticket input, overriding any field you like."""

    def _make(ticket_id: str = "T-1", **overrides) -> TicketCreate:
        values = {
            "ticket_id": ticket_id,
            "title": "VPN not connecting",
            "description": "Cannot connect to the office VPN from home.",
            "priority": TicketPriority.HIGH,
            "category": TicketCategory.NETWORK,
        }
        values.update(overrides)
        return TicketCreate(**values)

    return _make


@pytest.fixture
def make_engineer_data():
    """Factory: build valid engineer input, overriding any field you like."""

    def _make(engineer_id: str = "E-1", **overrides) -> EngineerCreate:
        values = {
            "engineer_id": engineer_id,
            "name": "Asha",
            "skills": {TicketCategory.NETWORK},
        }
        values.update(overrides)
        return EngineerCreate(**values)

    return _make