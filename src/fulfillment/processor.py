from __future__ import annotations

"""Order processor - polls for new orders and auto-fulfills them.

Uses DB to track processed orders (survives restarts).
"""

import logging
from datetime import datetime
from pathlib import Path

import yaml

from src.fulfillment.doudian import DoudianClient
from src.fulfillment.supplier import relay_order_to_supplier
from src.notify.feishu import send_feishu_message
from src.db.models import get_session, Order

logger = logging.getLogger(__name__)

PRODUCTS_CONFIG = Path(__file__).parent.parent.parent / "config" / "products.yaml"


class OrderProcessor:
    """Automated order fulfillment processor with DB persistence."""

    def __init__(self, merchant_id: str | None = None):
        self.merchant_id = merchant_id
        self.doudian = DoudianClient(merchant_id=merchant_id)

    async def process_new_orders(self) -> dict:
        """Poll for new orders and relay them to suppliers."""
        try:
            orders = await self.doudian.get_new_orders()
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            return {"error": str(e)}

        session = get_session()
        try:
            # Filter out already-processed orders via DB
            new_orders = []
            for o in orders:
                oid = o.get("shop_order_id", "")
                existing = session.query(Order).filter_by(order_id=oid).first()
                if not existing:
                    new_orders.append(o)

            if not new_orders:
                return {"processed": 0}

            results = []
            for order in new_orders:
                order_id = order.get("shop_order_id", "")
                try:
                    supplier_config = self._match_supplier(order)
                    result = await relay_order_to_supplier(order, supplier_config)

                    # Record in DB
                    db_order = Order(
                        order_id=order_id,
                        merchant_id=self.merchant_id,
                        product_key=self._extract_product_key(order),
                        status="relayed",
                        supplier_name=supplier_config.get("name", ""),
                        relay_method=supplier_config.get("contact_type", "feishu"),
                        amount=float(order.get("pay_amount", 0)) / 100,  # 分 → 元
                        created_at=datetime.utcnow(),
                    )
                    session.add(db_order)
                    results.append(result)
                    logger.info(f"Order {order_id} relayed to supplier")

                except Exception as e:
                    logger.error(f"Failed to process order {order_id}: {e}")
                    await send_feishu_message(f"⚠️ 订单处理失败\n订单号: {order_id}\n错误: {str(e)[:200]}")

            session.commit()
            return {"processed": len(results)}

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def update_tracking(self, order_id: str, logistics_code: str, tracking_no: str) -> dict:
        """Update tracking number for an order."""
        result = await self.doudian.ship_order(order_id, logistics_code, tracking_no)

        session = get_session()
        try:
            db_order = session.query(Order).filter_by(order_id=order_id).first()
            if db_order:
                db_order.status = "shipped"
                db_order.tracking_no = tracking_no
                db_order.logistics_code = logistics_code
                db_order.shipped_at = datetime.utcnow()
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        return {"status": "shipped", "order_id": order_id, "tracking": tracking_no}

    def _match_supplier(self, order: dict) -> dict:
        """Match an order to the right supplier based on product."""
        products = self._load_products()
        order_items = order.get("sku_order_list", [])

        for item in order_items:
            product_name = item.get("product_name", "")
            for key, product in products.items():
                name = product.get("name", "")
                short = product.get("short_name", "")
                if (name and name in product_name) or (short and short in product_name):
                    return product.get("supplier", {"contact_type": "feishu"})

        # Default fallback
        for product in products.values():
            if product.get("supplier"):
                return product["supplier"]
        return {"contact_type": "feishu"}

    def _extract_product_key(self, order: dict) -> str:
        """Try to match order to a product key."""
        products = self._load_products()
        for item in order.get("sku_order_list", []):
            product_name = item.get("product_name", "")
            for key, product in products.items():
                if product.get("name", "") in product_name:
                    return key
        return "unknown"

    @staticmethod
    def _load_products() -> dict:
        """Load products config with absolute path."""
        try:
            with open(PRODUCTS_CONFIG) as f:
                return yaml.safe_load(f).get("products", {})
        except FileNotFoundError:
            logger.error(f"Products config not found: {PRODUCTS_CONFIG}")
            return {}
