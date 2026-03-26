from __future__ import annotations

"""Supplier integration - relays orders to suppliers for fulfillment.

Supports multiple relay modes:
- feishu: Send order details via Feishu bot message
- api: Direct API call to supplier's system
- wechat: (manual) Format for copy-paste to WeChat
"""

import logging

from src.notify.feishu import send_feishu_message

logger = logging.getLogger(__name__)


async def relay_order_to_supplier(order: dict, supplier_config: dict) -> dict:
    """Relay an order to the supplier based on their configured contact method.

    Args:
        order: Order details from 抖店 API
        supplier_config: Supplier config from products.yaml

    Returns:
        Relay result with status
    """
    contact_type = supplier_config.get("contact_type", "feishu")

    if contact_type == "feishu":
        return await _relay_via_feishu(order, supplier_config)
    elif contact_type == "api":
        return await _relay_via_api(order, supplier_config)
    else:
        logger.warning(f"Unknown contact type: {contact_type}, falling back to feishu")
        return await _relay_via_feishu(order, supplier_config)


async def _relay_via_feishu(order: dict, supplier_config: dict) -> dict:
    """Send order to supplier via Feishu bot message."""
    # Extract order info
    order_id = order.get("shop_order_id", "unknown")
    items = order.get("sku_order_list", [{}])
    address_info = order.get("post_addr", {})

    item_lines = []
    for item in items:
        name = item.get("product_name", "")
        sku = item.get("sku_name", "")
        qty = item.get("item_num", 1)
        item_lines.append(f"  - {name} ({sku}) x{qty}")

    receiver = address_info.get("user_name", "")
    phone = address_info.get("user_phone", "")
    province = address_info.get("province", {}).get("name", "")
    city = address_info.get("city", {}).get("name", "")
    town = address_info.get("town", {}).get("name", "")
    detail = address_info.get("detail", "")
    full_address = f"{province}{city}{town}{detail}"

    message = f"""📦 **新订单 - 请发货**

订单号: {order_id}
商品:
{chr(10).join(item_lines)}

收件人: {receiver}
电话: {phone}
地址: {full_address}

⚠️ 发货后请回复运单号"""

    webhook_url = supplier_config.get("webhook_url") or ""
    if webhook_url:
        await send_feishu_message(message, webhook_url=webhook_url)
    else:
        await send_feishu_message(message)

    return {"status": "relayed", "method": "feishu", "order_id": order_id}


async def _relay_via_api(order: dict, supplier_config: dict) -> dict:
    """Relay order via supplier's API (custom per supplier)."""
    import httpx

    api_url = supplier_config.get("api_url", "")
    api_key = supplier_config.get("api_key", "")

    if not api_url:
        raise ValueError("Supplier API URL not configured")

    payload = {
        "order_id": order.get("shop_order_id"),
        "items": [
            {
                "product_name": item.get("product_name"),
                "sku": item.get("sku_name"),
                "quantity": item.get("item_num", 1),
            }
            for item in order.get("sku_order_list", [])
        ],
        "shipping_address": {
            "name": order.get("post_addr", {}).get("user_name"),
            "phone": order.get("post_addr", {}).get("user_phone"),
            "address": _extract_full_address(order.get("post_addr", {})),
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            api_url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()

    return {"status": "relayed", "method": "api", "order_id": order.get("shop_order_id")}


def _extract_full_address(addr: dict) -> str:
    """Extract full address string from 抖店 address structure."""
    parts = []
    for key in ["province", "city", "town"]:
        part = addr.get(key, {})
        if isinstance(part, dict):
            parts.append(part.get("name", ""))
        else:
            parts.append(str(part))
    parts.append(addr.get("detail", ""))
    return "".join(parts)
