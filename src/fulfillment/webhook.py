from __future__ import annotations

"""Webhook server - receives tracking number updates from suppliers.

Suppliers can POST tracking info here, which auto-updates 抖店 order status.

Endpoint: POST /webhook/tracking
Body: {"order_id": "xxx", "logistics_code": "yuantong", "tracking_no": "YT123456"}

Can also be triggered by parsing Feishu bot replies (future enhancement).
"""

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.fulfillment.processor import OrderProcessor

logger = logging.getLogger(__name__)

app = FastAPI(title="邑品引擎 - Supplier Webhook")
processor = OrderProcessor()


class TrackingUpdate(BaseModel):
    order_id: str
    logistics_code: str  # e.g., "yuantong", "shunfeng", "zhongtong"
    tracking_no: str


@app.post("/webhook/tracking")
async def receive_tracking(update: TrackingUpdate):
    """Receive tracking number from supplier and update 抖店."""
    try:
        result = await processor.update_tracking(
            order_id=update.order_id,
            logistics_code=update.logistics_code,
            tracking_no=update.tracking_no,
        )
        logger.info(f"Tracking updated: {update.order_id} → {update.tracking_no}")
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Tracking update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "yipin-engine-webhook"}
