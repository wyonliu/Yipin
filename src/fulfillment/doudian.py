from __future__ import annotations

"""抖店 Open Platform API client - order management and fulfillment."""

import hashlib
import hmac
import json
import logging
import time

import httpx

from config.settings import settings
from src.common.retry import with_retry

logger = logging.getLogger(__name__)


class DoudianClient:
    """Client for 抖店 Open Platform API."""

    def __init__(self, merchant_id: str | None = None):
        self.merchant_id = merchant_id
        self.base_url = settings.doudian_base_url.rstrip("/")

        if merchant_id:
            from src.common.tenant import get_merchant_credentials
            creds = get_merchant_credentials(merchant_id, "doudian")
            self.app_key = creds["app_id"] or settings.doudian_app_key
            self.app_secret = creds["app_secret"] or settings.doudian_app_secret
            self.shop_id = creds["shop_id"] or settings.doudian_shop_id
        else:
            self.app_key = settings.doudian_app_key
            self.app_secret = settings.doudian_app_secret
            self.shop_id = settings.doudian_shop_id

    def _sign(self, method: str, param_json: str, timestamp: str) -> str:
        """Generate HMAC-SHA256 signature per 抖店 docs.

        Sign string format: app_key + method + param_json + timestamp + app_secret
        (wrapped by app_secret on both sides)
        """
        sign_str = (
            f"{self.app_secret}"
            f"app_key{self.app_key}"
            f"method{method}"
            f"param_json{param_json}"
            f"timestamp{timestamp}"
            f"v2"
            f"{self.app_secret}"
        )
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    @with_retry(max_retries=3, base_delay=2.0, exceptions=(httpx.HTTPError, RuntimeError))
    async def _request(self, method: str, biz_params: dict) -> dict:
        """Make a signed API request to 抖店."""
        timestamp = str(int(time.time()))
        param_json = json.dumps(biz_params, separators=(",", ":"), ensure_ascii=False)
        sign = self._sign(method, param_json, timestamp)

        # 抖店 API uses method name in URL path: order.searchList → /order/searchList
        url_path = method.replace(".", "/")
        url = f"{self.base_url}/{url_path}"

        form_data = {
            "app_key": self.app_key,
            "method": method,
            "param_json": param_json,
            "timestamp": timestamp,
            "v": "2",
            "sign": sign,
            "sign_method": "md5",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=form_data)
            resp.raise_for_status()
            result = resp.json()

        err_no = result.get("err_no", -1)
        if err_no != 0:
            msg = result.get("message", "unknown error")
            logger.error(f"Doudian API [{method}] error {err_no}: {msg}")
            raise RuntimeError(f"Doudian API error: {err_no} - {msg}")

        return result.get("data", {})

    # ---- Order Management ----

    async def get_new_orders(self, page: int = 0, size: int = 100) -> list[dict]:
        """Fetch new paid orders that need fulfillment."""
        data = await self._request("order.searchList", {
            "order_status": 2,  # 待发货
            "page": page,
            "size": min(size, 100),
        })
        return data.get("shop_order_list", [])

    async def get_order_detail(self, order_id: str) -> dict:
        """Get full detail for a specific order."""
        data = await self._request("order.orderDetail", {
            "shop_order_id": order_id,
        })
        return data.get("shop_order_detail", {})

    async def ship_order(self, order_id: str, logistics_code: str, tracking_no: str) -> dict:
        """Push shipping information (tracking number) to fulfill an order."""
        return await self._request("order.logisticsAdd", {
            "shop_order_id": order_id,
            "logistics_code": logistics_code,
            "tracking_no": tracking_no,
        })

    async def get_order_count_by_status(self) -> dict:
        """Get count of orders by status for dashboard."""
        results = {}
        for status, label in [(2, "待发货"), (3, "已发货"), (4, "已完成")]:
            try:
                data = await self._request("order.searchList", {
                    "order_status": status, "page": 0, "size": 1,
                })
                results[label] = data.get("total", 0)
            except Exception:
                results[label] = -1
        return results
