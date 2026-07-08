"""Async SQLAlchemy engine + session factory + the get_db() dependency.

Replaces the earlier sync stub. The whole app is async (asyncpg) so the SSE
run stream and concurrent requests never block a worker thread.

Note: Alembic migrations run with a SYNC driver in migrations/env.py — the
app runs async here. Same database, two drivers, on purpose.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in app/models.py."""


async def get_db():
    """FastAPI dependency: yields a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
