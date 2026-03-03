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

    subparsers = parser.add_subparsers(dest="command")

    whales_parser = subparsers.add_parser("whales", help="Display whale rankings")
    whales_parser.add_argument(
        "address",
        nargs="?",
        default=None,
        help="Show stats for a single wallet",
    )
    whales_parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="Include below-threshold wallets",
    )
    whales_parser.add_argument(
        "--mode",
        choices=["consistent", "highroller", "frequent"],
        default=None,
        help="Scoring mode override for display only (does not update DB)",
    )
    whales_parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Rolling window in days",
    )

    return parser


def _abbrev_address(address: str) -> str:
    """Abbreviate a wallet address: first 8 chars + '...' + last 6 chars."""
    if len(address) <= 14:
        return address
    return address[:8] + "..." + address[-6:]


def _fmt_win_rate(win_rate) -> str:
    if win_rate is None:
        return "N/A"
    return f"{win_rate * 100:.1f}%"


def _fmt_pnl(pnl) -> str:
    if pnl is None:
        return "N/A"
    return f"${pnl:.2f}"


async def _show_whale_table(session, show_all: bool, mode, days, settings) -> None:
    from sqlalchemy import select
    from arbiter.db.models import Wallet
    from arbiter.scoring.whales import _apply_scores

    query = select(Wallet)
    if not show_all:
        query = query.where(Wallet.is_tracked == True)
    query = query.order_by(Wallet.score.desc()).limit(20)

    result = await session.execute(query)
    wallets = result.scalars().all()

    if not wallets:
        print("No whales found. Run the service to ingest trades and score wallets.")
        return

    # If mode differs from settings or days is set, recompute scores in-memory
    display_mode = mode or settings.whale_score_mode
    if mode is not None and mode != settings.whale_score_mode:
        rows = [
            {
                "address": w.address,
                "win_rate": w.win_rate,
                "total_volume": w.total_volume,
                "total_trades": w.total_trades,
                "win_volume": w.win_volume,
                "total_pnl": w.total_pnl,
                "pnl_trend": w.pnl_trend,
                "is_tracked": w.is_tracked,
            }
            for w in wallets
        ]
        _apply_scores(rows, mode=display_mode)
        rows.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    else:
        rows = [
            {
                "address": w.address,
                "win_rate": w.win_rate,
                "total_pnl": w.total_pnl,
                "total_trades": w.total_trades,
                "score": w.score,
                "is_tracked": w.is_tracked,
            }
            for w in wallets
        ]

    header = f"{'Rank':<5} {'Address':<20} {'Win Rate':>10} {'Total P&L':>12} {'Trades':>8} {'Score':>10}"
    print(header)
    print("-" * len(header))

    for i, row in enumerate(rows, start=1):
        abbr = _abbrev_address(row["address"])
        win_rate_str = _fmt_win_rate(row.get("win_rate"))
        pnl_str = _fmt_pnl(row.get("total_pnl"))
        trades = row.get("total_trades") or 0
        score = row.get("score")
        score_str = f"{score:.4f}" if score is not None else "N/A"
        print(f"{i:<5} {abbr:<20} {win_rate_str:>10} {pnl_str:>12} {trades:>8} {score_str:>10}")


async def _show_wallet_detail(session, address: str) -> None:
    from sqlalchemy import select, func
    from arbiter.db.models import Market, Trade, Wallet

    # Query wallet by exact or prefix match
    query = select(Wallet).where(Wallet.address.ilike(f"{address}%"))
    result = await session.execute(query)
    wallet = result.scalars().first()

    if wallet is None:
        print(f"Wallet not found: {address}")
        return

    print(f"\nWallet: {wallet.address}")
    print(f"  Win Rate:      {_fmt_win_rate(wallet.win_rate)}")
    print(f"  Total P&L:     {_fmt_pnl(wallet.total_pnl)}")
    print(f"  Total Volume:  {_fmt_pnl(wallet.total_volume)}")
    print(f"  Win Volume:    {_fmt_pnl(wallet.win_volume)}")
    print(f"  PnL Trend:     {wallet.pnl_trend:.4f}" if wallet.pnl_trend is not None else "  PnL Trend:     N/A")
    print(f"  Score:         {wallet.score:.4f}" if wallet.score is not None else "  Score:         N/A")
    print(f"  Tracked:       {wallet.is_tracked}")
    print(f"  Last Scored:   {wallet.last_scored_at}")

    # Fetch last 10 markets this wallet traded on
    trades_query = (
        select(Trade, Market)
        .join(Market, Trade.market_id == Market.id)
        .where(Trade.wallet_address == wallet.address)
        .order_by(Trade.timestamp.desc())
        .limit(10)
    )
    trades_result = await session.execute(trades_query)
    rows = trades_result.all()

    if rows:
        print("\n  Recent Markets:")
        seen_markets: set[int] = set()
        for trade, market in rows:
            if market.id in seen_markets:
                continue
            seen_markets.add(market.id)
            question = market.question[:60]
            status = "resolved" if market.resolved else "open"
            print(f"    [{status}] {question}")


async def display_whales(args: argparse.Namespace, settings) -> None:
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    try:
        async with session_factory() as session:
            if args.address:
                await _show_wallet_detail(session, args.address)
            else:
                await _show_whale_table(
                    session,
                    show_all=args.show_all,
                    mode=args.mode,
                    days=args.days,
                    settings=settings,
                )
    finally:
        await engine.dispose()


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

    if getattr(args, "command", None) == "whales":
        asyncio.run(display_whales(args, settings))
    else:
        asyncio.run(main(args, settings))


if __name__ == "__main__":
    main_sync()
