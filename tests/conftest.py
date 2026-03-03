"""Shared fixtures for arbiter tests."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arbiter.clients.polymarket import Trade as ClientTrade
from arbiter.config import Settings
from arbiter.db.models import Base


# ---------------------------------------------------------------------------
# Settings fixture — minimal config, no real DB/Discord needed
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    return Settings(
        database_url="postgresql+asyncpg://fake:fake@localhost/fake",
        discord_webhook_url="https://discord.com/api/webhooks/fake/fake",
        ingestion_interval_seconds=300,
        ingestion_page_size=500,
        ingestion_batch_size=100,
    )


# ---------------------------------------------------------------------------
# In-memory SQLite engine + session factory (for integration tests)
# ---------------------------------------------------------------------------

@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(async_engine):
    return async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

def make_client_trade(
    proxy_wallet: str = "0xabc",
    side: str = "BUY",
    size: float = 10.0,
    price: float = 0.65,
    timestamp: int = 1_700_000_000,
    condition_id: str = "0xcondition1",
    outcome: str | None = "Yes",
) -> ClientTrade:
    return ClientTrade(
        proxyWallet=proxy_wallet,
        side=side,
        size=size,
        price=price,
        timestamp=timestamp,
        conditionId=condition_id,
        outcome=outcome,
    )
