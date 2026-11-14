"""Application settings, read from environment variables with safe defaults."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./ticket_routing.db"
    num_workers: int = 3
    poll_timeout: float = 0.2
    queue_maxsize: int = 0  # 0 = unbounded


def load_settings() -> Settings:
    defaults = Settings()
    return Settings(
        database_url=os.getenv("TICKETS_DATABASE_URL", defaults.database_url),
        num_workers=int(os.getenv("TICKETS_NUM_WORKERS", defaults.num_workers)),
        poll_timeout=float(os.getenv("TICKETS_POLL_TIMEOUT", defaults.poll_timeout)),
        queue_maxsize=int(os.getenv("TICKETS_QUEUE_MAXSIZE", defaults.queue_maxsize)),
    )