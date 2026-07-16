from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# check_same_thread=False is required for SQLite with FastAPI's threaded workers.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models (models added in a later phase)."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
