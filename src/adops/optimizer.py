from __future__ import annotations

"""Auto-optimizer - monitors campaigns and makes scaling/killing decisions.

Core logic:
- Every 2 hours, scan all active campaigns
- Scale winners (low CPA) → increase budget by 50%
- Kill losers (high CPA or zero conversion after spend threshold) → pause
- Feed performance data back to creative engine
"""

import logging
from datetime import date, datetime

from config.settings import settings
from src.adops.qianchuan import QianchuanClient
from src.db.models import get_session, Campaign
from src.notify.feishu import send_feishu_message

logger = logging.getLogger(__name__)


class CampaignOptimizer:
    """Automated campaign optimization engine."""

    def __init__(self, merchant_id: str | None = None):
        self.merchant_id = merchant_id
        self.client = QianchuanClient(merchant_id=merchant_id)
        self.target_cpa = settings.target_cpa
        self.stop_loss = settings.stop_loss_threshold
        self.kill_cpa_ratio = settings.kill_cpa_ratio
        self.max_budget = settings.max_budget_per_campaign

    async def run_optimization_cycle(self, active_ad_ids: list[str]) -> dict:
        """Run one optimization cycle across all active campaigns."""
        if not active_ad_ids:
            return {"scaled": [], "killed": [], "maintained": []}

        today = date.today().strftime("%Y-%m-%d")

        try:
            reports = await self.client.get_campaign_reports(
                ad_ids=active_ad_ids, start_date=today, end_date=today
            )
        except Exception as e:
            logger.error(f"Failed to fetch campaign reports: {e}")
            return {"error": str(e)}

        actions = {"scaled": [], "killed": [], "maintained": []}
        session = get_session()

        try:
            for report in reports:
                ad_id = str(report.get("ad_id", ""))
                spend = float(report.get("stat_cost", 0))
                conversions = int(report.get("convert_cnt", 0))
                cpa = float(report.get("conversion_cost", 0)) if conversions > 0 else 0
                roi = float(report.get("prepay_and_pay_order_roi", 0))
                gmv = float(report.get("pay_order_amount", 0))

                action = self._decide_action(spend, conversions, cpa, roi)

                if action == "scale":
                    new_budget = self._calc_scale_budget(spend)
                    try:
                        await self.client.update_campaign_budget(ad_id, new_budget)
                        actions["scaled"].append({"ad_id": ad_id, "cpa": cpa, "roi": roi, "new_budget": new_budget})
                    except Exception as e:
                        logger.error(f"Failed to scale {ad_id}: {e}")

                elif action == "kill":
                    try:
                        await self.client.update_campaign_status([ad_id], "AD_STATUS_DISABLE")
                        actions["killed"].append({"ad_id": ad_id, "spend": spend, "cpa": cpa})
                        # Update DB
                        db_campaign = session.query(Campaign).filter_by(ad_id=ad_id).first()
                        if db_campaign:
                            db_campaign.status = "killed"
                            db_campaign.killed_at = datetime.utcnow()
                    except Exception as e:
                        logger.error(f"Failed to kill {ad_id}: {e}")
                else:
                    actions["maintained"].append({"ad_id": ad_id, "cpa": cpa})

                # Update campaign stats in DB
                db_campaign = session.query(Campaign).filter_by(ad_id=ad_id).first()
                if db_campaign:
                    db_campaign.total_spend = spend
                    db_campaign.total_conversions = conversions
                    db_campaign.total_gmv = gmv
                    db_campaign.best_roi = max(db_campaign.best_roi or 0, roi)

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        await self._notify_summary(actions)
        return actions

    def _decide_action(self, spend: float, conversions: int, cpa: float, roi: float) -> str:
        """Decide: "scale" | "kill" | "maintain"."""
        # Spent enough but zero conversions → kill
        if spend >= self.stop_loss and conversions == 0:
            return "kill"

        # CPA too high → kill
        if conversions > 0 and cpa > self.target_cpa * self.kill_cpa_ratio:
            return "kill"

        # CPA excellent and enough data → scale
        if conversions >= 2 and cpa < self.target_cpa * 0.8:
            return "scale"

        # ROI excellent → scale
        if roi > 2.0 and conversions >= 1:
            return "scale"

        return "maintain"

    def _calc_scale_budget(self, current_spend: float) -> float:
        """Calculate new budget: current × 1.5, capped at max."""
        # FIX: scale by 1.5x (not 3x as before)
        new_budget = current_spend * settings.scale_up_ratio
        new_budget = max(new_budget, 200)  # Floor
        new_budget = min(new_budget, self.max_budget)  # Cap
        return round(new_budget, 0)

    async def _notify_summary(self, actions: dict) -> None:
        """Send optimization summary to Feishu."""
        scaled = actions.get("scaled", [])
        killed = actions.get("killed", [])

        if not scaled and not killed:
            return

        lines = ["📊 **投放优化巡检**\n"]
        if scaled:
            lines.append(f"🚀 加量 {len(scaled)} 条:")
            for item in scaled:
                lines.append(f"  - {item['ad_id']}: CPA ¥{item['cpa']:.0f}, ROI {item['roi']:.1f}, 新预算 ¥{item['new_budget']:.0f}")
        if killed:
            lines.append(f"⛔ 关停 {len(killed)} 条:")
            for item in killed:
                lines.append(f"  - {item['ad_id']}: 消耗 ¥{item['spend']:.0f}, CPA ¥{item['cpa']:.0f}")
        lines.append(f"✅ 维持 {len(actions.get('maintained', []))} 条")

        await send_feishu_message("\n".join(lines))


async def get_top_performing_creatives(
    days: int = 7, limit: int = 5, merchant_id: str | None = None,
) -> list[dict]:
    """Get top creatives from DB with full metadata for feedback loop."""
    session = get_session()
    try:
        q = session.query(Campaign).filter(
            Campaign.total_conversions > 0, Campaign.best_roi > 0,
        )
        if merchant_id:
            q = q.filter(Campaign.merchant_id == merchant_id)
        campaigns = q.order_by(Campaign.best_roi.desc()).limit(limit).all()
        return [
            {
                "ad_id": c.ad_id,
                "cpa": c.total_spend / max(c.total_conversions, 1),
                "roi": c.best_roi,
                "angle": c.angle or "",
                "hook_style": c.hook[:30] if c.hook else "",
            }
            for c in campaigns
        ]
    finally:
        session.close()
