"""
SQLAlchemy engine and session factory, built once from settings.DATABASE_URL.

`pool_pre_ping=True` transparently recovers from dropped connections (e.g. the
Postgres service restarting under the app). Import `get_session()` for a
transactional scope, or `engine` directly for lightweight reads.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings

if not settings.database_url:
    raise RuntimeError(
        "DATABASE_URL is not configured. Set it in .env (dev) or the service "
        "environment (prod) — see docs/deploy.md."
    )

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def get_session():
    """Transactional scope: commits on success, rolls back on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
