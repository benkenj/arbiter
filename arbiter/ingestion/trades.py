import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import insert as sa_insert, select

from arbiter.clients.polymarket import PolymarketClient, Trade as ClientTrade
from arbiter.config import Settings
from arbiter.db.models import Market, Trade

logger = logging.getLogger(__name__)


def _trade_to_db_row(trade: ClientTrade, market_id: int) -> dict:
    return {
        "wallet_address": trade.proxy_wallet,
        "market_id": market_id,
        "side": trade.side,
        "size": trade.size,
        "price": trade.price,
        "timestamp": datetime.fromtimestamp(trade.timestamp, tz=timezone.utc),
        "outcome": trade.outcome,
    }


async def _bulk_insert_trades(session, trade_rows: list[dict]) -> None:
    if not trade_rows:
        return
    await session.execute(sa_insert(Trade).values(trade_rows))
    # Caller commits after updating last_ingested_at


async def ingest_market(session, client: PolymarketClient, market: Market, page_size: int) -> int:
    """
    Fetch and insert new trades for one market.
    Updates market.last_ingested_at to the newest trade's timestamp.
    Returns count of new trades inserted. Raises on error (caller catches).
    """
    trades = await client.get_trades_for_market(
        condition_id=market.condition_id,
        since=market.last_ingested_at,
        page_size=page_size,
    )
    if not trades:
        return 0

    rows = [_trade_to_db_row(t, market.id) for t in trades]
    await _bulk_insert_trades(session, rows)

    # Update watermark to newest trade timestamp (trades are newest-first from API)
    max_ts = max(t.timestamp for t in trades)
    market.last_ingested_at = datetime.fromtimestamp(max_ts, tz=timezone.utc)
    await session.commit()
    return len(rows)


async def run_ingestion_cycle(
    settings: Settings, session_factory, client: PolymarketClient
) -> tuple[int, int, int]:
    """
    Run one full ingestion cycle across all active markets.
    Returns (markets_processed, total_trades_inserted, failure_count).
    """
    # Fetch market list outside per-market sessions — avoid long session hold during HTTP
    async with session_factory() as session:
        result = await session.execute(
            select(Market).where(
                Market.active == True,
                Market.condition_id.is_not(None),
            )
        )
        markets = result.scalars().all()

    processed = 0
    total_trades = 0
    failures = 0

    for market in markets[: settings.ingestion_batch_size]:
        try:
            async with session_factory() as session:
                # Re-fetch within a fresh session for the update
                mkt = await session.get(Market, market.id)
                if mkt is None:
                    continue
                count = await ingest_market(session, client, mkt, settings.ingestion_page_size)
                total_trades += count
                processed += 1
        except Exception as exc:
            failures += 1
            cid_prefix = (market.condition_id or "")[:16]
            logger.error(
                "[ingestion] market %s (%s) failed: %s",
                market.external_id,
                cid_prefix,
                exc,
            )

    return processed, total_trades, failures


async def ingestion_loop(settings: Settings, session_factory, client: PolymarketClient) -> None:
    while True:
        t0 = time.monotonic()
        try:
            processed, total_trades, failures = await run_ingestion_cycle(
                settings, session_factory, client
            )
            elapsed = time.monotonic() - t0
            logger.info(
                "[ingestion] cycle complete in %.1fs — %d markets, %d trades inserted, %d failures",
                elapsed,
                processed,
                total_trades,
                failures,
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error("[ingestion] cycle failed after %.1fs: %s", elapsed, exc)
        await asyncio.sleep(settings.ingestion_interval_seconds)
