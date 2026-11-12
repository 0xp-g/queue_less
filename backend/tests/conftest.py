"""Shared fixtures. Integration and API tests need PostgreSQL (QL_TEST_DATABASE_URL)."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.db.session import build_session_factory

TEST_DB_URL = os.environ.get(
    "QL_TEST_DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/queueless_test"
)
HERE = os.path.dirname(__file__)


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Run the real Alembic migration once per session (tests the migration too)."""
    cfg = Config(os.path.join(HERE, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "..", "alembic"))
    cfg.attributes["database_url"] = TEST_DB_URL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return TEST_DB_URL


@pytest.fixture
def settings(migrated_db) -> Settings:
    return Settings(
        database_url=migrated_db,
        event_transport="memory",
        enable_background_tasks=False,
        join_rate_limit_per_min=0,
        db_pool_size=50,
        db_max_overflow=20,
    )


@pytest.fixture
async def engine(settings):
    eng = create_async_engine(settings.database_url, pool_size=50, max_overflow=20)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE queue_events, tickets, counters, queues, staff_users, venues "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return build_session_factory(engine)
