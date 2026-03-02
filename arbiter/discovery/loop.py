import asyncio
import logging
import sys
import time
from datetime import datetime, timezone

import sqlalchemy.exc
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from arbiter.clients.polymarket import Market as ClientMarket
from arbiter.config import Settings
from arbiter.db.models import Market

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_DB_FAILURES = 5


def _is_binary(market: ClientMarket) -> bool:
    outcomes = [o.lower() for o in (market.outcomes or [])]
    return outcomes == ["yes", "no"]


def _apply_filters(
    markets: list[ClientMarket], settings: Settings
) -> tuple[list[ClientMarket], int]:
    passing: list[ClientMarket] = []
    filtered_out = 0
    for m in markets:
        if settings.market_binary_only and not _is_binary(m):
            filtered_out += 1
            continue
        if (m.volume or 0) < settings.market_min_volume:
            filtered_out += 1
            continue
        if (m.liquidity or 0) < settings.market_min_liquidity:
            filtered_out += 1
            continue
        passing.append(m)
    return passing, filtered_out


def _parse_end_date(end_date_str: str | None) -> datetime | None:
    if not end_date_str:
        return None
    try:
        dt = datetime.fromisoformat(end_date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _to_db_row(market: ClientMarket) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "external_id": market.id,
        "question": market.question,
        "description": market.description,
        "end_date": _parse_end_date(market.end_date),
        "resolved": market.resolved,
        "closed": market.closed,
        "yes_price": market.yes_price,
        "liquidity": market.liquidity,
        "volume": market.volume,
        "active": True,
        "condition_id": market.condition_id,
        "fetched_at": now,
        "created_at": now,
    }


_UPSERT_BATCH_SIZE = 500  # 500 rows × 13 cols = 6500 params, well under PG's 65535 limit


async def upsert_markets(session, market_rows: list[dict]) -> int:
    if not market_rows:
        return 0
    for i in range(0, len(market_rows), _UPSERT_BATCH_SIZE):
        batch = market_rows[i : i + _UPSERT_BATCH_SIZE]
        stmt = insert(Market).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_id"],
            set_={
                "question": stmt.excluded.question,
                "description": stmt.excluded.description,
                "end_date": stmt.excluded.end_date,
                "resolved": stmt.excluded.resolved,
                "closed": stmt.excluded.closed,
                "yes_price": stmt.excluded.yes_price,
                "liquidity": stmt.excluded.liquidity,
                "volume": stmt.excluded.volume,
                "active": stmt.excluded.active,
                "condition_id": stmt.excluded.condition_id,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await session.execute(stmt)
    await session.commit()
    return len(market_rows)


async def run_discovery_cycle(
    settings: Settings,
    session_factory,
    client,
    cycle_start_dt: datetime,
) -> tuple[int, int, int]:
    all_markets = await client.fetch_all_active_markets()
    passing, filtered_out = _apply_filters(all_markets, settings)
    market_rows = [_to_db_row(m) for m in passing]

    async with session_factory() as session:
        upserted = await upsert_markets(session, market_rows)
        result = await session.execute(
            select(func.count()).select_from(Market).where(Market.created_at >= cycle_start_dt)
        )
        new_count = result.scalar_one()

    return upserted, new_count, filtered_out


async def discovery_loop(settings: Settings, session_factory, client) -> None:
    consecutive_db_failures = 0
    while True:
        t0 = time.monotonic()
        cycle_start_dt = datetime.now(timezone.utc)
        try:
            upserted, new_count, filtered = await run_discovery_cycle(
                settings, session_factory, client, cycle_start_dt
            )
            consecutive_db_failures = 0
            elapsed = time.monotonic() - t0
            logger.info(
                "[discovery] cycle complete in %.1fs — %d upserted, %d new, %d filtered out",
                elapsed,
                upserted,
                new_count,
                filtered,
            )
        except sqlalchemy.exc.OperationalError as exc:
            consecutive_db_failures += 1
            elapsed = time.monotonic() - t0
            logger.error(
                "[discovery] DB error on cycle (failure %d/%d) after %.1fs: %s",
                consecutive_db_failures,
                MAX_CONSECUTIVE_DB_FAILURES,
                elapsed,
                exc,
            )
            if consecutive_db_failures >= MAX_CONSECUTIVE_DB_FAILURES:
                logger.critical(
                    "[discovery] DB permanently unreachable after %d consecutive failures — exiting for process manager restart",
                    MAX_CONSECUTIVE_DB_FAILURES,
                )
                sys.exit(1)
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error("[discovery] cycle failed after %.1fs: %s", elapsed, exc)
        await asyncio.sleep(settings.discovery_interval_seconds)
