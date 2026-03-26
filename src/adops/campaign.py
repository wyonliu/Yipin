from __future__ import annotations

"""Campaign manager - bridges creative pipeline with ad platform.

All state persisted to DB. Survives restarts.
"""

import logging
from datetime import datetime

from src.adops.qianchuan import QianchuanClient
from src.db.models import get_session, Campaign, Creative

logger = logging.getLogger(__name__)


class CampaignManager:
    """Manages the lifecycle of ad campaigns with DB persistence."""

    def __init__(self, merchant_id: str | None = None):
        self.merchant_id = merchant_id
        self.client = QianchuanClient(merchant_id=merchant_id)

    async def launch_creative(
        self,
        creative: dict,
        product_id: str,
        budget: float = 100.0,
        target_cpa: float | None = None,
    ) -> dict:
        """Upload a creative video and launch it as an ad campaign."""
        video_path = creative["video_path"]
        cpa = target_cpa or creative.get("target_cpa", 25.0)

        # Step 1: Upload video
        logger.info(f"Uploading creative {creative['id']}...")
        upload_result = await self.client.upload_video(video_path)
        video_id = upload_result.get("video_id", "")
        if not video_id:
            raise RuntimeError(f"Upload returned no video_id: {upload_result}")

        # Step 2: Create campaign
        prefix = "[AI邑品]" if self.merchant_id else "yipin"
        campaign_name = f"{prefix}_{creative['product_key']}_{creative.get('angle', 'auto')}_{creative['id']}"

        logger.info(f"Creating campaign: {campaign_name}")
        campaign_result = await self.client.create_campaign(
            video_id=video_id,
            product_id=product_id,
            budget=budget,
            target_cpa=cpa,
            campaign_name=campaign_name,
        )

        ad_id = str(campaign_result.get("ad_id", ""))
        if not ad_id:
            raise RuntimeError(f"Campaign creation returned no ad_id: {campaign_result}")

        # Persist to DB
        session = get_session()
        try:
            db_campaign = Campaign(
                ad_id=ad_id,
                merchant_id=self.merchant_id,
                creative_id=creative["id"],
                product_key=creative["product_key"],
                video_id=video_id,
                budget=budget,
                target_cpa=cpa,
                angle=creative.get("angle", ""),
                hook=creative.get("hook", ""),
                status="active",
                created_at=datetime.utcnow(),
            )
            session.add(db_campaign)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        return {
            "ad_id": ad_id,
            "creative_id": creative["id"],
            "product_key": creative["product_key"],
            "status": "active",
        }

    async def launch_batch(
        self,
        creatives: list[dict],
        product_id: str,
        budget_per_campaign: float = 100.0,
    ) -> list[dict]:
        """Launch a batch of creatives as campaigns."""
        campaigns = []
        for creative in creatives:
            try:
                campaign = await self.launch_creative(
                    creative, product_id, budget=budget_per_campaign
                )
                campaigns.append(campaign)
            except Exception as e:
                logger.error(f"Failed to launch creative {creative['id']}: {e}")

        logger.info(f"Launched {len(campaigns)}/{len(creatives)} campaigns")
        return campaigns

    @staticmethod
    def get_active_ad_ids(merchant_id: str | None = None) -> list[str]:
        """Get active ad IDs from DB, optionally filtered by merchant."""
        session = get_session()
        try:
            q = session.query(Campaign.ad_id).filter_by(status="active")
            if merchant_id:
                q = q.filter_by(merchant_id=merchant_id)
            return [c.ad_id for c in q.all()]
        finally:
            session.close()
