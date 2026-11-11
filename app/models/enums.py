"""Shared enumerations for tickets."""
from enum import StrEnum


class TicketPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TicketCategory(StrEnum):
    NETWORK = "NETWORK"
    HARDWARE = "HARDWARE"
    SOFTWARE = "SOFTWARE"
    ACCESS = "ACCESS"
    OTHER = "OTHER"


class TicketStatus(StrEnum):
    OPEN = "OPEN"              # created, not yet submitted for processing
    QUEUED = "QUEUED"          # waiting in the FIFO queue
    PROCESSING = "PROCESSING"  # a worker has picked it up
    ASSIGNED = "ASSIGNED"      # an engineer has been assigned
    RESOLVED = "RESOLVED"      # work finished
    FAILED = "FAILED"          # processing failed (can be re-queued)