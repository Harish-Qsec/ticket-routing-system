"""Engineer management and ticket-to-engineer matching.

Engineers live in a dict keyed by engineer_id, so lookup by ID is O(1)
on average.

Thread safety: worker threads assign engineers while API threads add them.
"Is this engineer free? Then mark them busy" must happen as one step, and
iterating the dict while another thread inserts into it raises RuntimeError.
queue.Queue cannot protect this dict, so we use one lock.
"""
import threading

from app.exceptions import (
    DuplicateEngineerError,
    EngineerNotFoundError,
    NoAvailableEngineerError,
)
from app.models.engineer import Engineer
from app.models.enums import TicketCategory
from app.schemas.engineer import EngineerCreate


class EngineerService:
    def __init__(self) -> None:
        self._engineers: dict[str, Engineer] = {}
        self._lock = threading.Lock()

    def _get(self, engineer_id: str) -> Engineer:
        # Caller must already hold self._lock.
        try:
            return self._engineers[engineer_id]
        except KeyError:
            raise EngineerNotFoundError(engineer_id) from None

    def add_engineer(self, data: EngineerCreate) -> Engineer:
        with self._lock:
            if data.engineer_id in self._engineers:
                raise DuplicateEngineerError(data.engineer_id)
            engineer = Engineer(
                engineer_id=data.engineer_id,
                name=data.name,
                skills=set(data.skills),
                is_available=data.is_available,
            )
            self._engineers[engineer.engineer_id] = engineer
            return engineer

    def get_engineer(self, engineer_id: str) -> Engineer:
        with self._lock:
            return self._get(engineer_id)

    def list_engineers(self) -> list[Engineer]:
        with self._lock:
            return list(self._engineers.values())

    def assign_engineer(self, category: TicketCategory) -> Engineer:
        """Pick the first available engineer with the skill and mark them busy.

        Dicts keep insertion order, so "first" means "added earliest".
        This is O(E) in the number of engineers. The check and the update
        happen under one lock, so two workers can never get the same engineer.
        """
        with self._lock:
            for engineer in self._engineers.values():
                if engineer.is_available and category in engineer.skills:
                    engineer.is_available = False
                    return engineer
            raise NoAvailableEngineerError(category)

    def release_engineer(self, engineer_id: str) -> Engineer:
        with self._lock:
            engineer = self._get(engineer_id)
            engineer.is_available = True
            return engineer