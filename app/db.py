"""Database engine and session plumbing.

One engine per process, built from `DATABASE_URL` (docs/ARCHITECTURE.md). The rules live
in `app/repositories.py`: nothing here decides who may see what.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    """A pooled engine. `pool_pre_ping` survives a database that restarts under us."""
    return create_engine(normalise_database_url(database_url), pool_pre_ping=True, future=True)


def normalise_database_url(database_url: str) -> str:
    """Plain `postgresql://` would pick psycopg2, which is not installed. Use psycopg 3."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
