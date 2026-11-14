"""Shared fixtures. Each test gets its own temporary SQLite database file,
so tests are isolated from each other and never touch real project data."""
import pytest

from app.database import create_db_engine, init_db, make_session_factory, sqlite_url
from app.models.enums import TicketCategory, TicketPriority
from app.schemas.engineer import EngineerCreate
from app.schemas.ticket import TicketCreate
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService


@pytest.fixture
def engine(tmp_path):
    engine = create_db_engine(sqlite_url(tmp_path / "test.db"))
    init_db(engine)
    yield engine
    engine.dispose()  # close connections so Windows can delete the file


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def ticket_service(session_factory) -> TicketService:
    return TicketService(session_factory)


@pytest.fixture
def engineer_service(session_factory) -> EngineerService:
    return EngineerService(session_factory)


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