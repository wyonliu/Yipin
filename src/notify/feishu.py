from __future__ import annotations

"""Feishu (飞书) bot notification - sends alerts and reports."""

import httpx

from config.settings import settings


async def send_feishu_message(
    text: str,
    webhook_url: str | None = None,
    msg_type: str = "text",
) -> bool:
    """Send a message via Feishu webhook bot.

    Args:
        text: Message content (supports markdown-like formatting)
        webhook_url: Override webhook URL (defaults to settings)
        msg_type: "text" or "interactive" (card)

    Returns:
        True if sent successfully
    """
    url = webhook_url or settings.feishu_webhook_url
    if not url:
        return False

    if msg_type == "text":
        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
    else:
        payload = {
            "msg_type": "interactive",
            "card": _build_card(text),
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            return result.get("code") == 0
    except Exception:
        return False


async def send_daily_report(report: dict) -> bool:
    """Send formatted daily report to Feishu."""
    lines = [
        "📊 **邑品引擎 - 每日报告**\n",
        f"日期: {report.get('date', 'N/A')}",
        f"总消耗: ¥{report.get('total_spend', 0):.0f}",
        f"总GMV: ¥{report.get('total_gmv', 0):.0f}",
        f"总订单: {report.get('total_orders', 0)}",
        f"整体ROI: {report.get('overall_roi', 0):.2f}",
        f"平均CPA: ¥{report.get('avg_cpa', 0):.1f}",
        "",
        f"今日生产素材: {report.get('creatives_produced', 0)} 条",
        f"在投计划: {report.get('active_campaigns', 0)} 条",
        f"今日关停: {report.get('killed_today', 0)} 条",
        f"今日加量: {report.get('scaled_today', 0)} 条",
    ]

    # Top performers
    if report.get("top_creatives"):
        lines.append("\n🏆 **今日TOP素材:**")
        for i, creative in enumerate(report["top_creatives"][:3], 1):
            lines.append(
                f"  {i}. [{creative.get('angle', '')}] "
                f"ROI {creative.get('roi', 0):.1f} | "
                f"CPA ¥{creative.get('cpa', 0):.0f} | "
                f"GMV ¥{creative.get('gmv', 0):.0f}"
            )

    # Net profit
    profit = report.get("total_gmv", 0) * 0.3 - report.get("total_spend", 0)
    lines.append(f"\n💰 **预估净利润: ¥{profit:.0f}**")

    return await send_feishu_message("\n".join(lines))


def _build_card(text: str) -> dict:
    """Build a Feishu interactive card from text."""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "邑品引擎通知"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": text},
        ],
    }
