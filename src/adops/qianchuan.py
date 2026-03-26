from __future__ import annotations

"""巨量千川 API client - handles authentication, campaign management, and reporting."""

import hashlib
import time

import httpx

from config.settings import settings


class QianchuanClient:
    """Client for 巨量千川 Open API."""

    def __init__(self, merchant_id: str | None = None):
        self.merchant_id = merchant_id
        self.base_url = settings.qianchuan_base_url

        if merchant_id:
            from src.common.tenant import get_merchant_credentials
            creds = get_merchant_credentials(merchant_id, "qianchuan")
            self.app_id = creds["app_id"] or settings.qianchuan_app_id
            self.app_secret = creds["app_secret"] or settings.qianchuan_app_secret
            self.access_token = creds["access_token"]
            self.advertiser_id = creds["advertiser_id"]
        else:
            self.app_id = settings.qianchuan_app_id
            self.app_secret = settings.qianchuan_app_secret
            self.access_token = settings.qianchuan_access_token
            self.advertiser_id = settings.qianchuan_advertiser_id

    def _headers(self) -> dict:
        return {
            "Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    # ---- OAuth2 Token Management ----

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """Refresh the access token using a refresh token."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/oauth2/refresh_token/",
                json={
                    "app_id": self.app_id,
                    "secret": self.app_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        self.access_token = data["data"]["access_token"]
        return data["data"]

    # ---- Creative / Material Upload ----

    async def upload_video(self, video_path: str, filename: str | None = None) -> dict:
        """Upload a video creative to the ad platform.

        Returns:
            Dict with video_id for use in campaign creation
        """
        if filename is None:
            filename = video_path.split("/")[-1]

        async with httpx.AsyncClient(timeout=120) as client:
            with open(video_path, "rb") as f:
                resp = await client.post(
                    f"{self.base_url}/2/file/video/ad/",
                    headers={"Access-Token": self.access_token},
                    data={"advertiser_id": self.advertiser_id},
                    files={"video_file": (filename, f, "video/mp4")},
                )
                resp.raise_for_status()
                return resp.json()["data"]

    # ---- Campaign Management ----

    async def create_campaign(
        self,
        video_id: str,
        product_id: str,
        budget: float,
        target_cpa: float,
        campaign_name: str = "",
    ) -> dict:
        """Create an ad campaign (广告计划) on 千川.

        This creates a complete plan: campaign + ad group + creative in one call
        using 千川's simplified "programmatic creative" mode.
        """
        payload = {
            "advertiser_id": self.advertiser_id,
            "campaign_name": campaign_name or f"yipin_auto_{int(time.time())}",
            "campaign_type": "FEED",  # 信息流
            "marketing_goal": "VIDEO_PROM_GOODS",  # 短视频带货
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": budget,
            "bid_type": "BID_TYPE_OCPM",  # oCPM智能出价
            "cpa_bid": target_cpa,
            "deep_bid_type": "DEEP_BID_DEFAULT",
            "video_id": video_id,
            "product_id": product_id,
            "delivery_range": "DEFAULT",  # 默认投放范围
            "schedule_type": "SCHEDULE_FROM_NOW",
            "audience": {
                "district": "CITY",  # 按城市定向
                "gender": "GENDER_UNLIMITED",
                "age": ["AGE_18_23", "AGE_24_30", "AGE_31_40", "AGE_41_49"],
                "auto_extend_enabled": True,  # 智能放量
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/v1.0/qianchuan/ad/create/",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["data"]

    async def update_campaign_budget(self, ad_id: str, new_budget: float) -> dict:
        """Update the daily budget for a campaign."""
        payload = {
            "advertiser_id": self.advertiser_id,
            "ad_id": ad_id,
            "budget": new_budget,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/v1.0/qianchuan/ad/budget/update/",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["data"]

    async def update_campaign_status(self, ad_ids: list[str], opt_status: str) -> dict:
        """Update campaign status (enable/disable).

        opt_status: "AD_STATUS_ENABLE" or "AD_STATUS_DISABLE"
        """
        payload = {
            "advertiser_id": self.advertiser_id,
            "ad_ids": ad_ids,
            "opt_status": opt_status,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/v1.0/qianchuan/ad/status/update/",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["data"]

    # ---- Reporting ----

    async def get_campaign_reports(
        self,
        ad_ids: list[str] | None = None,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict]:
        """Get performance reports for campaigns.

        Returns list of dicts with: ad_id, spend, impressions, clicks,
        conversions, cpa, roi, etc.
        """
        payload = {
            "advertiser_id": self.advertiser_id,
            "start_date": start_date,
            "end_date": end_date,
            "fields": [
                "ad_id", "ad_name", "stat_cost", "show_cnt", "click_cnt",
                "convert_cnt", "conversion_cost", "pay_order_count",
                "pay_order_amount", "prepay_and_pay_order_roi",
            ],
        }
        if ad_ids:
            payload["filtering"] = {"ad_ids": ad_ids}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/v1.0/qianchuan/report/ad/get/",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return data.get("list", [])

    async def get_realtime_report(self, ad_id: str) -> dict:
        """Get real-time (today's) performance for a single campaign."""
        from datetime import date

        today = date.today().strftime("%Y-%m-%d")
        reports = await self.get_campaign_reports(
            ad_ids=[ad_id], start_date=today, end_date=today
        )
        return reports[0] if reports else {}
