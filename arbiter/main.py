import argparse
import asyncio
import logging
import sys

from sqlalchemy import text

from arbiter.clients.polymarket import PolymarketClient
from arbiter.config import load_settings, print_config_summary
from arbiter.db.session import make_engine, make_session_factory
from arbiter.discovery.loop import discovery_loop
from arbiter.ingestion.trades import ingestion_loop


def configure_logging(level: str = "INFO", verbose: bool = False) -> None:
    effective_level = logging.DEBUG if verbose else getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=effective_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Arbiter whale copy-trading alert service",
        prog="arbiter",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate config and connectivity, then exit",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging (same as LOG_LEVEL=DEBUG)",
    )
    return parser


async def check_db_health(engine, retries: int = 5, backoff: float = 2.0) -> None:
    """Attempt DB connection with exponential backoff. Exit 1 on failure."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logging.info("Database connection OK")
            return
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                wait = backoff ** attempt
                logging.warning(
                    f"DB unreachable (attempt {attempt}/{retries}), retrying in {wait:.0f}s..."
                )
                await asyncio.sleep(wait)
    logging.error(f"Database unreachable after {retries} attempts: {last_exc}")
    sys.exit(1)


async def check_gamma_health(client: PolymarketClient) -> None:
    """Fetch one market page from Gamma API to confirm reachability."""
    try:
        markets = await client._fetch_page(offset=0, limit=1)
        if markets:
            logging.info(f"Gamma API reachable (sample: {markets[0].question[:60]!r})")
        else:
            logging.info("Gamma API reachable (no markets returned)")
    except Exception as exc:
        logging.error(f"Gamma API unreachable: {exc}")
        sys.exit(1)


async def run_checks(settings) -> None:
    """Run DB + API health checks. Used by both --check mode and normal startup."""
    engine = make_engine(settings.database_url)
    try:
        await check_db_health(engine)
    finally:
        await engine.dispose()

    async with PolymarketClient() as client:
        await check_gamma_health(client)


async def main(args: argparse.Namespace, settings) -> None:
    print_config_summary(settings)

    if args.check:
        logging.info("Running connectivity checks...")
        await run_checks(settings)
        logging.info("All checks passed. Service is ready.")
        return

    # Normal startup: run checks then continue to service loops
    await run_checks(settings)
    logging.info("Service ready. Starting discovery and ingestion loops.")

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    try:
        async with PolymarketClient() as client:
            await asyncio.gather(
                discovery_loop(settings, session_factory, client),
                ingestion_loop(settings, session_factory, client),
            )
    finally:
        await engine.dispose()


def main_sync() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Load settings FIRST — if validation fails, errors go to stderr before logging is set up
    settings = load_settings()

    # Configure logging with settings + CLI flag
    configure_logging(level=settings.log_level, verbose=args.verbose)

    asyncio.run(main(args, settings))


if __name__ == "__main__":
    main_sync()
