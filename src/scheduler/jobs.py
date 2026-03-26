from __future__ import annotations

"""Scheduler - all automated jobs with DB-persisted state.

Survives restarts: checks DB for today's completed jobs before running.

Schedule:
  06:00  Daily creative production
  08:00  Upload & launch new campaigns
  Every 2h  Optimization cycle (scale/kill)
  Every 5m  Order polling & fulfillment
  23:00  Daily report generation
"""

import asyncio
import logging
from datetime import datetime, date

from src.creative.pipeline import produce_daily_batch
from src.adops.campaign import CampaignManager
from src.adops.optimizer import CampaignOptimizer, get_top_performing_creatives
from src.fulfillment.processor import OrderProcessor
from src.analytics.reporter import generate_daily_report
from src.notify.feishu import send_daily_report, send_feishu_message
from src.db.models import get_session, JobRun

logger = logging.getLogger(__name__)

# Global singletons for backward compat (single-merchant / no merchant_id mode)
campaign_manager = CampaignManager()
order_processor = OrderProcessor()
optimizer = CampaignOptimizer()


def _job_ran_today(job_name: str) -> bool:
    """Check if a job already ran today (DB-persisted, survives restart)."""
    session = get_session()
    try:
        today = date.today().strftime("%Y-%m-%d")
        run = (
            session.query(JobRun)
            .filter_by(job_name=job_name, run_date=today, success=True)
            .first()
        )
        return run is not None
    finally:
        session.close()


def _record_job_run(job_name: str, summary: str = "", success: bool = True):
    """Record a job execution in DB."""
    session = get_session()
    try:
        session.add(JobRun(
            job_name=job_name,
            run_date=date.today().strftime("%Y-%m-%d"),
            completed_at=datetime.utcnow(),
            result_summary=summary[:500] if summary else "",
            success=success,
        ))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


# ---- Cached state within a single scheduler run ----
_today_creatives: list[dict] = []


async def job_produce_creatives(merchant_id: str | None = None):
    """06:00 - Generate daily batch of ad creatives."""
    global _today_creatives

    job_key = f"produce_creatives:{merchant_id or 'global'}"
    if _job_ran_today(job_key):
        logger.info(f"Creative production already ran today for {merchant_id or 'global'}, skipping")
        return

    logger.info(f"Starting daily creative production for {merchant_id or 'global'}...")
    try:
        top_performers = await get_top_performing_creatives(
            days=7, limit=5, merchant_id=merchant_id,
        )
        creatives = await produce_daily_batch(
            top_performers=top_performers, merchant_id=merchant_id,
        )
        _today_creatives.extend(creatives)

        summary = f"{len(creatives)} creatives generated"
        _record_job_run(job_key, summary)

        await send_feishu_message(
            f"🎬 今日素材生产完成: {len(creatives)} 条\n"
            + "\n".join(
                f"  - [{c['product_name']}] {c['angle']}: {c['hook'][:20]}..."
                for c in creatives[:5]
            )
        )
    except Exception as e:
        logger.error(f"Creative production failed: {e}")
        _record_job_run(job_key, str(e), success=False)
        await send_feishu_message(f"❌ 素材生产失败: {str(e)[:200]}")


async def job_launch_campaigns(
    product_ids: dict[str, str] | None = None,
    merchant_id: str | None = None,
):
    """08:00 - Upload creatives and launch as ad campaigns."""
    global _today_creatives

    job_key = f"launch_campaigns:{merchant_id or 'global'}"
    if _job_ran_today(job_key):
        logger.info(f"Campaign launch already ran today for {merchant_id or 'global'}, skipping")
        return

    # Filter creatives for this merchant
    my_creatives = [c for c in _today_creatives if c.get("merchant_id") == merchant_id]
    if not my_creatives:
        logger.info(f"No creatives to launch for {merchant_id or 'global'}")
        return

    # Resolve product IDs: from merchant DB or from passed-in map
    if merchant_id:
        from src.common.tenant import get_merchant_products
        merchant_products = get_merchant_products(merchant_id)
        pid_map = {k: v.get("doudian_product_id", "") for k, v in merchant_products.items()}
    else:
        pid_map = product_ids or {}

    mgr = CampaignManager(merchant_id=merchant_id)

    logger.info(f"Launching {len(my_creatives)} creatives for {merchant_id or 'global'}...")
    launched = []
    for creative in my_creatives:
        product_id = pid_map.get(creative["product_key"], "")
        if not product_id:
            logger.warning(f"No product ID for {creative['product_key']}, skipping")
            continue
        try:
            campaign = await mgr.launch_creative(
                creative, product_id=product_id, budget=100.0
            )
            launched.append(campaign)
        except Exception as e:
            logger.error(f"Failed to launch {creative['id']}: {e}")

    summary = f"{len(launched)}/{len(my_creatives)} launched"
    _record_job_run(job_key, summary)
    await send_feishu_message(f"🚀 投放启动: {summary}")

    # Remove launched creatives from buffer
    launched_ids = {c["creative_id"] for c in launched}
    _today_creatives = [c for c in _today_creatives if c["id"] not in launched_ids]


async def job_optimize(merchant_id: str | None = None):
    """Every 2 hours - Run optimization cycle."""
    active_ids = CampaignManager.get_active_ad_ids(merchant_id=merchant_id)
    if not active_ids:
        return

    opt = CampaignOptimizer(merchant_id=merchant_id) if merchant_id else optimizer
    logger.info(f"Optimizing {len(active_ids)} active campaigns for {merchant_id or 'global'}...")
    try:
        await opt.run_optimization_cycle(active_ids)
    except Exception as e:
        logger.error(f"Optimization cycle failed: {e}")


async def job_process_orders(merchant_id: str | None = None):
    """Every 5 minutes - Poll and process new orders."""
    proc = OrderProcessor(merchant_id=merchant_id) if merchant_id else order_processor
    try:
        result = await proc.process_new_orders()
        if result.get("processed", 0) > 0:
            logger.info(f"Processed {result['processed']} new orders for {merchant_id or 'global'}")
    except Exception as e:
        logger.error(f"Order processing failed: {e}")


async def job_daily_report(merchant_id: str | None = None):
    """23:00 - Generate and send daily report."""
    job_key = f"daily_report:{merchant_id or 'global'}"
    if _job_ran_today(job_key):
        return

    try:
        report = await generate_daily_report(merchant_id=merchant_id)
        await send_daily_report(report)
        _record_job_run(job_key, f"ROI={report.get('overall_roi', 0):.2f}")
    except Exception as e:
        logger.error(f"Daily report failed: {e}")
        _record_job_run(job_key, str(e), success=False)
        await send_feishu_message(f"❌ 日报生成失败: {str(e)[:200]}")


async def run_scheduler(
    product_ids: dict[str, str] | None = None,
    merchant_ids: list[str] | None = None,
):
    """Main scheduler loop. Runs all jobs on their schedules.

    In multi-tenant mode (merchant_ids provided), iterates over all active
    merchants. In single-tenant mode, uses global singletons + product_ids.

    All state persisted to DB — safe to restart at any time.
    """
    logger.info("Scheduler started")
    await send_feishu_message("✅ 邑品引擎已启动")

    last_optimize_hour = -1

    while True:
        now = datetime.now()
        hour = now.hour
        minute = now.minute

        # Resolve merchant list (refresh each loop for dynamic adds)
        if merchant_ids:
            active_merchants = merchant_ids
        else:
            from src.common.tenant import get_all_active_merchants
            merchants = get_all_active_merchants()
            active_merchants = [m.id for m in merchants] if merchants else [None]

        try:
            for mid in active_merchants:
                # 06:00 - Produce creatives
                if hour == 6 and minute < 5:
                    await job_produce_creatives(merchant_id=mid)

                # 08:00 - Launch campaigns
                if hour == 8 and minute < 5:
                    await job_launch_campaigns(
                        product_ids=product_ids, merchant_id=mid,
                    )

                # Every even hour, :00-:04 - Optimize
                if hour % 2 == 0 and minute < 5 and hour != last_optimize_hour:
                    await job_optimize(merchant_id=mid)

                # Every 5 minutes - Process orders
                if minute % 5 == 0:
                    await job_process_orders(merchant_id=mid)

                # 23:00 - Daily report
                if hour == 23 and minute < 5:
                    await job_daily_report(merchant_id=mid)

            if hour % 2 == 0 and minute < 5:
                last_optimize_hour = hour

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}", exc_info=True)

        await asyncio.sleep(60)
