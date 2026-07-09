"""Async SQLAlchemy engine + session factory + the get_db() dependency.

Replaces the earlier sync stub. The whole app is async (asyncpg) so the SSE
run stream and concurrent requests never block a worker thread.

The engine is created LAZILY (first get_db() call) so importing this module —
and therefore app.models and every router — never touches the database. That
keeps the app importable/bootable before .env is finalized or asyncpg is
installed; a misconfigured DATABASE_URL fails on first request, not at import.

Note: Alembic (migrations/env.py, async template) runs on the same asyncpg
driver and pulls its URL from the same settings — one driver, one env surface.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in app/models.py."""


@lru_cache(maxsize=1)
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Build the engine + session factory once, on first use."""
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency: yields a request-scoped async session."""
    async with _sessionmaker()() as session:
        yield session
