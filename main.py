"""
fashionvoid-bot · main.py
─────────────────────────────────────────────────────────────────────────────
Entry point for the FashionVoid Asia Monitor Bot.

Boots the scheduler, initialises all scrapers and notification channels,
and renders a live Rich dashboard in the terminal.

Usage
─────
  python main.py                  # run with config.yaml in the same directory
  python main.py --config /path   # custom config path
  python main.py --once           # run all scrapers once then exit (testing)
  python main.py --platform mercari_jp  # run only one platform
─────────────────────────────────────────────────────────────────────────────
"""

import argparse
import asyncio
import logging
import signal
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console

from dashboard import app as dashboard_app
from dashboard import init as dashboard_init
from db import Database
from notifications import EmailAlert, PushAlert, SMSAlert
from scrapers import SCRAPER_REGISTRY
from utils import CurrencyConverter, ProxyManager, Translator

# ── Logging setup ─────────────────────────────────────────────────────────────

def _configure_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("log_file", "fashionvoid.log")

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "playwright", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger("fashionvoid.main")

# ── Rich console ──────────────────────────────────────────────────────────────

console = Console()

# ── Banner ────────────────────────────────────────────────────────────────────

_BANNER = """
[dim]─────────────────────────────────────────────────────────[/dim]
[bold white]  F A S H I O N V O I D[/bold white]  [dim]Asia Monitor[/dim]
[dim]─────────────────────────────────────────────────────────[/dim]
"""

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8888


# ─── Config loader ────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─── Scan job ─────────────────────────────────────────────────────────────────

async def _scan_job(
    platform_name: str,
    scraper,
    notifications: list,
    stats_store: dict,
) -> None:
    """
    Single scheduled scan cycle for one platform.
    Updates stats_store in place for the live dashboard.
    """
    start = datetime.utcnow()
    try:
        count = await scraper.run(notifications)
        stats_store[platform_name]["last_run"] = start.strftime("%H:%M:%S")
        stats_store[platform_name]["new_found"] += count
        stats_store[platform_name]["status"] = "OK"
        if count:
            logger.info(f"[{platform_name}] ✓ {count} new listing(s)")
    except Exception as exc:
        stats_store[platform_name]["status"] = "ERR"
        logger.error(f"[{platform_name}] Scan failed: {exc}", exc_info=True)



# ─── Main ─────────────────────────────────────────────────────────────────────

async def main(args) -> None:
    # ── Load config ───────────────────────────────────────────────────
    config_path = args.config
    if not Path(config_path).exists():
        console.print(f"[red]Config not found: {config_path}[/red]")
        sys.exit(1)

    config = load_config(config_path)
    _configure_logging(config)

    console.print(_BANNER)
    logger.info("FashionVoid Asia Monitor starting…")

    # ── Shared services ───────────────────────────────────────────────
    db = Database(config["database"]["path"])
    translator = Translator(config)
    fx = CurrencyConverter(config)
    proxy = ProxyManager(config)

    # Pre-warm currency rates
    await fx._get_rates()

    # ── Notification channels ─────────────────────────────────────────
    notifications = [
        EmailAlert(config, db),
        SMSAlert(config, db),
        PushAlert(config, db),
    ]

    # ── Scraper instances ─────────────────────────────────────────────
    target_platforms = (
        [args.platform] if args.platform else list(SCRAPER_REGISTRY.keys())
    )

    scrapers: dict[str, object] = {}
    for name in target_platforms:
        cls = SCRAPER_REGISTRY.get(name)
        if cls:
            scrapers[name] = cls(config, db, translator, fx, proxy)
        else:
            logger.warning(f"Unknown platform: {name}")

    if not scrapers:
        console.print("[red]No valid platforms configured.[/red]")
        sys.exit(1)

    # ── Stats store (live dashboard state) ────────────────────────────
    stats_store: dict[str, dict] = {
        name: {"last_run": "—", "new_found": 0, "status": "—"}
        for name in scrapers
    }

    # ── One-shot mode ─────────────────────────────────────────────────
    if args.once:
        console.print("[dim]Running all scrapers once…[/dim]")
        tasks = [
            _scan_job(name, scraper, notifications, stats_store)
            for name, scraper in scrapers.items()
        ]
        await asyncio.gather(*tasks)
        db_stats = db.stats()
        console.print(
            f"\n[bold white]Done.[/bold white]  "
            f"Total: {db_stats['total_listings']}  "
            f"Suspicious: {db_stats['suspicious']}  "
            f"Alerts: {db_stats['alerts_sent']}"
        )
        return

    # ── Scheduler ─────────────────────────────────────────────────────
    intervals = config.get("intervals_seconds", {})
    scheduler = AsyncIOScheduler(timezone="UTC")

    for name, scraper in scrapers.items():
        interval = intervals.get(name, 60)
        scheduler.add_job(
            _scan_job,
            trigger=IntervalTrigger(seconds=interval),
            args=[name, scraper, notifications, stats_store],
            id=f"scan_{name}",
            next_run_time=datetime.utcnow(),   # run immediately on start
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"[{name}] Scheduled every {interval}s")

    scheduler.start()

    # ── Dashboard ─────────────────────────────────────────────────────
    dashboard_init(db, stats_store, config, scheduler=scheduler, config_path=args.config)

    url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
    console.print(f"\n[bold white]Dashboard →[/bold white] [dim]{url}[/dim]")
    console.print("[dim]Opening in browser… Press Ctrl+C to stop.[/dim]\n")

    # Small delay so the server is ready before browser opens
    async def _open_browser():
        await asyncio.sleep(1.2)
        webbrowser.open(url)

    asyncio.ensure_future(_open_browser())

    # ── uvicorn web server (runs until Ctrl+C) ────────────────────────
    cfg = uvicorn.Config(
        dashboard_app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(cfg)
    try:
        await server.serve()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        server.should_exit = True
        scheduler.shutdown(wait=False)
        logger.info("FashionVoid Monitor stopped.")


# ─── CLI entry ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FashionVoid Asia Monitor Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py\n"
            "  python main.py --once\n"
            "  python main.py --platform mercari_jp\n"
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run all scrapers once and exit (useful for testing)",
    )
    parser.add_argument(
        "--platform",
        choices=list(SCRAPER_REGISTRY.keys()),
        help="Run only the specified platform",
    )

    cli_args = parser.parse_args()
    try:
        asyncio.run(main(cli_args))
    except KeyboardInterrupt:
        pass
