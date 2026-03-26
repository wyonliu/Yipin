from __future__ import annotations

"""邑品引擎 - AI千川代投平台 (全自动素材生成+投放+优化+履约+获客)

Usage:
    python main.py serve                # Start web server (landing page + API)
    python main.py run                  # Start full automation scheduler
    python main.py creatives            # Generate creatives only (test)
    python main.py optimize             # Run one optimization cycle
    python main.py orders               # Process pending orders
    python main.py report               # Generate today's report
    python main.py init-db              # Initialize database tables

Options:
    --merchant-id=<id>                  # Run for a specific merchant
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("yipin")

# No hardcoded product IDs — all merchant data lives in DB (multi-tenant)


async def cmd_run(merchant_id: str | None = None):
    """Start the full automation scheduler."""
    from src.common.startup import validate_all, print_startup_banner, StartupError
    from src.db.models import init_db
    from src.scheduler.jobs import run_scheduler

    try:
        warnings = validate_all()
    except StartupError as e:
        logger.error(f"FATAL: {e}")
        sys.exit(1)

    init_db()
    print_startup_banner(warnings)
    await run_scheduler(
        merchant_ids=[merchant_id] if merchant_id else None,
    )


async def cmd_creatives(merchant_id: str | None = None):
    """Generate creatives only (for testing the pipeline)."""
    from src.db.models import init_db
    from src.creative.pipeline import produce_daily_batch

    init_db()
    logger.info(f"Generating test creative batch for {merchant_id or 'default'}...")
    creatives = await produce_daily_batch(merchant_id=merchant_id)
    for c in creatives:
        logger.info(f"  [{c['product_name']}] {c['angle']}: {c['video_path']}")
    logger.info(f"Done. {len(creatives)} creatives generated.")


async def cmd_optimize(merchant_id: str | None = None):
    """Run one optimization cycle."""
    from src.db.models import init_db
    from src.adops.campaign import CampaignManager
    from src.adops.optimizer import CampaignOptimizer

    init_db()
    opt = CampaignOptimizer(merchant_id=merchant_id)
    active_ids = CampaignManager.get_active_ad_ids(merchant_id=merchant_id)
    if not active_ids:
        logger.info("No active campaigns to optimize.")
        return
    actions = await opt.run_optimization_cycle(active_ids)
    logger.info(f"Optimization done: scaled={len(actions.get('scaled', []))}, killed={len(actions.get('killed', []))}")


async def cmd_orders(merchant_id: str | None = None):
    """Process pending orders."""
    from src.db.models import init_db
    from src.fulfillment.processor import OrderProcessor

    init_db()
    processor = OrderProcessor(merchant_id=merchant_id)
    result = await processor.process_new_orders()
    logger.info(f"Order processing done: {result}")


async def cmd_report(merchant_id: str | None = None):
    """Generate and print today's report."""
    from src.db.models import init_db
    from src.analytics.reporter import generate_daily_report

    init_db()
    report = await generate_daily_report(merchant_id=merchant_id)
    for k, v in report.items():
        if k != "top_creatives":
            logger.info(f"  {k}: {v}")


def cmd_init_db():
    """Initialize database tables."""
    from src.db.models import init_db
    engine = init_db()
    logger.info(f"Database initialized: {engine.url}")


def cmd_serve():
    """Start the web server (landing page + API + OAuth)."""
    import uvicorn
    from src.db.models import init_db
    init_db()
    logger.info("Starting web server on http://0.0.0.0:8000")
    uvicorn.run("src.growth.server:app", host="0.0.0.0", port=8000, reload=True)


COMMANDS = {
    "run": cmd_run,
    "creatives": cmd_creatives,
    "optimize": cmd_optimize,
    "orders": cmd_orders,
    "report": cmd_report,
    "init-db": cmd_init_db,
    "serve": cmd_serve,
}


def _parse_merchant_id() -> str | None:
    """Extract --merchant-id=VALUE from sys.argv."""
    for arg in sys.argv:
        if arg.startswith("--merchant-id="):
            return arg.split("=", 1)[1]
        if arg == "--merchant-id" and sys.argv.index(arg) + 1 < len(sys.argv):
            return sys.argv[sys.argv.index(arg) + 1]
    return None


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS.keys())}")
        print("Options: --merchant-id=<id>  (run for a specific merchant)")
        sys.exit(1)

    command = sys.argv[1]
    handler = COMMANDS[command]
    merchant_id = _parse_merchant_id()

    if command in ("init-db", "serve"):
        handler()  # sync commands, no merchant_id needed
    else:
        asyncio.run(handler(merchant_id=merchant_id))


if __name__ == "__main__":
    main()
