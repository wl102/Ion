import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base


def _default_sqlite_url() -> str:
    db_path = Path.home() / ".ion" / "ion.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


class Database:
    """Database connection manager supporting SQLite, MySQL, and PostgreSQL."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv("ION_DATABASE_URL") or _default_sqlite_url()
        # SQLite-specific: allow same-thread access for sync usage
        connect_args = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine = create_engine(self.database_url, connect_args=connect_args, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def get_session(self) -> Generator[Session, None, None]:
        """Yield a database session for dependency injection or context use."""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def init_db(self):
        """Create all tables."""
        Base.metadata.create_all(bind=self.engine)


# Singleton default instance
_default_db: Database | None = None


def get_default_db() -> Database:
    global _default_db
    if _default_db is None:
        _default_db = Database()
        _default_db.init_db()
    return _default_db
