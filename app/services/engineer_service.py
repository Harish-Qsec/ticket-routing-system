"""Engineer management and ticket-to-engineer matching, persisted in SQLite.

Assignment uses optimistic concurrency: pick a candidate, then claim it with
"UPDATE ... WHERE id = ? AND is_available" and check how many rows changed.
If another worker claimed it first the UPDATE changes 0 rows and we simply
try the next candidate. No Python lock is needed.
"""
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.exceptions import (
    DuplicateEngineerError,
    EngineerNotFoundError,
    NoAvailableEngineerError,
)
from app.models.engineer import Engineer, EngineerSkill
from app.models.enums import TicketCategory
from app.schemas.engineer import EngineerCreate


class EngineerService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self._session_factory

    @staticmethod
    def _get(session: Session, engineer_id: str) -> Engineer:
        engineer = session.scalars(
            select(Engineer)
            .where(Engineer.engineer_id == engineer_id)
            .execution_options(populate_existing=True)
        ).first()
        if engineer is None:
            raise EngineerNotFoundError(engineer_id)
        return engineer

    @staticmethod
    def _first_available(session: Session, category: TicketCategory) -> Engineer | None:
        """The earliest-added available engineer with the skill, or None."""
        return session.scalars(
            select(Engineer)
            .join(EngineerSkill, EngineerSkill.engineer_pk == Engineer.id)
            .where(EngineerSkill.category == category, Engineer.is_available.is_(True))
            .order_by(Engineer.id)
            .limit(1)
        ).first()

    def add_engineer(self, data: EngineerCreate) -> Engineer:
        with session_scope(self._session_factory) as session:
            engineer = Engineer(
                engineer_id=data.engineer_id,
                name=data.name,
                is_available=data.is_available,
                skill_rows=[EngineerSkill(category=c) for c in sorted(data.skills)],
            )
            session.add(engineer)
            try:
                session.flush()
            except IntegrityError:
                raise DuplicateEngineerError(data.engineer_id) from None
            return engineer

    def get_engineer(self, engineer_id: str) -> Engineer:
        with session_scope(self._session_factory) as session:
            return self._get(session, engineer_id)

    def list_engineers(self) -> list[Engineer]:
        with session_scope(self._session_factory) as session:
            return list(session.scalars(select(Engineer).order_by(Engineer.id)))

    def assign_engineer(
        self, category: TicketCategory, *, session: Session | None = None
    ) -> Engineer:
        """Reserve the first available engineer with the skill.

        If the caller passes a session, the reservation joins the caller's
        transaction, so it is rolled back together with everything else if
        a later step fails.
        """
        with session_scope(self._session_factory, session) as active:
            while True:
                candidate = self._first_available(active, category)
                if candidate is None:
                    raise NoAvailableEngineerError(category)
                claimed = active.execute(
                    update(Engineer)
                    .where(Engineer.id == candidate.id, Engineer.is_available.is_(True))
                    .values(is_available=False)
                    .execution_options(synchronize_session=False)
                )
                if claimed.rowcount == 1:
                    active.refresh(candidate)  # reload so is_available reads False
                    return candidate
                # 0 rows: someone else claimed it first. Look for the next one.

    def release_engineer(self, engineer_id: str, *, session: Session | None = None) -> Engineer:
        with session_scope(self._session_factory, session) as active:
            result = active.execute(
                update(Engineer)
                .where(Engineer.engineer_id == engineer_id)
                .values(is_available=True)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 0:
                raise EngineerNotFoundError(engineer_id)
            return self._get(active, engineer_id)