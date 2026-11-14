"""Database engine, session handling and shared column types."""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path

from sqlalchemy import DateTime, Enum, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Parent class of every ORM model."""


class UTCDateTime(TypeDecorator):
    """Stores timezone-aware datetimes as naive UTC and returns them aware.

    SQLite has no timezone support, so without this a value read back from
    the database would silently lose its tzinfo.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime: use a timezone-aware UTC value")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def enum_type(enum_class: type) -> Enum:
    """A VARCHAR column plus a CHECK constraint listing the allowed values."""
    return Enum(enum_class, native_enum=False, create_constraint=True, length=20)


def sqlite_url(path: str | Path) -> str:
    """Build a SQLite URL from a file path (also correct for Windows paths)."""
    return f"sqlite:///{Path(path).as_posix()}"


def create_db_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {}
    if is_sqlite:
        # check_same_thread=False: the pool hands each connection to one
        # thread at a time, so sharing connections across threads is safe.
        # timeout: wait up to 30 s for another writer instead of failing.
        connect_args = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(database_url, connect_args=connect_args)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")   # off by default in SQLite!
            cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
            cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False keeps loaded attributes readable after commit,
    # so objects we return remain usable once their session is closed.
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables (safe to call repeatedly)."""
    # Importing the model modules registers their tables on Base.metadata.
    import app.models.engineer  # noqa: F401
    import app.models.ticket  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session], session: Session | None = None
) -> Iterator[Session]:
    """One unit of work.

    If the caller passes a session, use it and let the caller commit (so
    several service calls can share ONE transaction). Otherwise open a new
    session, commit on success, and always close it; closing without a
    commit rolls everything back.
    """
    if session is not None:
        yield session
        return
    with session_factory() as new_session:
        yield new_session
        new_session.commit()