"""Domain-specific exceptions.

Services raise these; the API layer (Phase 6) translates them into HTTP
status codes. Keeping them here means services never import FastAPI.
"""


class TicketSystemError(Exception):
    """Base class for every error raised by our own business logic."""


class TicketNotFoundError(TicketSystemError):
    def __init__(self, ticket_id: str) -> None:
        super().__init__(f"Ticket '{ticket_id}' not found")
        self.ticket_id = ticket_id


class DuplicateTicketError(TicketSystemError):
    def __init__(self, ticket_id: str) -> None:
        super().__init__(f"Ticket '{ticket_id}' already exists")
        self.ticket_id = ticket_id


class InvalidStatusTransitionError(TicketSystemError):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"Cannot change status from {current} to {requested}")
        self.current = current
        self.requested = requested


class EngineerNotFoundError(TicketSystemError):
    def __init__(self, engineer_id: str) -> None:
        super().__init__(f"Engineer '{engineer_id}' not found")
        self.engineer_id = engineer_id


class DuplicateEngineerError(TicketSystemError):
    def __init__(self, engineer_id: str) -> None:
        super().__init__(f"Engineer '{engineer_id}' already exists")
        self.engineer_id = engineer_id


class NoAvailableEngineerError(TicketSystemError):
    def __init__(self, category: str) -> None:
        super().__init__(f"No available engineer with skill '{category}'")
        self.category = category


class QueueFullError(TicketSystemError):
    def __init__(self, capacity: int) -> None:
        super().__init__(f"Queue is full (capacity {capacity})")
        self.capacity = capacity