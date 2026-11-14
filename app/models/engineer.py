"""Engineer tables: one row per engineer plus one row per skill."""
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, enum_type
from app.models.enums import TicketCategory


class Engineer(Base):
    __tablename__ = "engineers"

    id: Mapped[int] = mapped_column(primary_key=True)  # surrogate key, gives insertion order
    engineer_id: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    is_available: Mapped[bool] = mapped_column(default=True)
    skill_rows: Mapped[list["EngineerSkill"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def skills(self) -> set[TicketCategory]:
        return {row.category for row in self.skill_rows}


class EngineerSkill(Base):
    """Many-to-many link between an engineer and a ticket category."""

    __tablename__ = "engineer_skills"

    engineer_pk: Mapped[int] = mapped_column(
        ForeignKey("engineers.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[TicketCategory] = mapped_column(
        enum_type(TicketCategory), primary_key=True
    )