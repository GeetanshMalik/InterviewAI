from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from anyio import to_thread

from config import settings

try:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
except Exception:  # pragma: no cover - lets static checks run before deps are installed.
    AsyncSession = Any  # type: ignore
    async_sessionmaker = None  # type: ignore
    create_async_engine = None  # type: ignore


engine = None
AsyncSessionLocal = None

if settings.database_url and create_async_engine is not None:
    engine = create_async_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def create_all_tables() -> None:
    """Apply Postgres migrations when production persistence is enabled.

    Development keeps using the JSON-backed store unless
    POSTGRES_PERSISTENCE_ENABLED=true. Production applies migrations through the
    repository manager before the API starts serving requests.
    """

    from services.repositories.manager import persistence_manager

    await to_thread.run_sync(persistence_manager.apply_migrations)


async def close_db() -> None:
    if engine is not None:
        await engine.dispose()


@asynccontextmanager
async def session_context() -> AsyncGenerator[AsyncSession | None, None]:
    if AsyncSessionLocal is None:
        yield None
        return

    async with AsyncSessionLocal() as session:
        yield session


async def get_db() -> AsyncGenerator[AsyncSession | None, None]:
    async with session_context() as session:
        yield session
