from __future__ import annotations

"""Analytics reporter - generates daily/weekly performance reports."""

from datetime import date

from src.adops.qianchuan import QianchuanClient


async def generate_daily_report(
    report_date: date | None = None,
    merchant_id: str | None = None,
) -> dict:
    """Generate a daily performance report.

    Aggregates: total spend, GMV, orders, ROI, top creatives, etc.
    """
    report_date = report_date or date.today()
    date_str = report_date.strftime("%Y-%m-%d")

    client = QianchuanClient(merchant_id=merchant_id)

    try:
        reports = await client.get_campaign_reports(
            start_date=date_str, end_date=date_str
        )
    except Exception:
        reports = []

    total_spend = sum(float(r.get("stat_cost", 0)) for r in reports)
    total_gmv = sum(float(r.get("pay_order_amount", 0)) for r in reports)
    total_orders = sum(int(r.get("pay_order_count", 0)) for r in reports)
    total_conversions = sum(int(r.get("convert_cnt", 0)) for r in reports)

    overall_roi = total_gmv / total_spend if total_spend > 0 else 0
    avg_cpa = total_spend / total_conversions if total_conversions > 0 else 0

    # Find top creatives by ROI
    with_conversions = [r for r in reports if int(r.get("convert_cnt", 0)) > 0]
    top_creatives = sorted(
        with_conversions,
        key=lambda r: float(r.get("prepay_and_pay_order_roi", 0)),
        reverse=True,
    )[:5]

    top_creative_list = [
        {
            "ad_id": r["ad_id"],
            "ad_name": r.get("ad_name", ""),
            "roi": float(r.get("prepay_and_pay_order_roi", 0)),
            "cpa": float(r.get("conversion_cost", 0)),
            "gmv": float(r.get("pay_order_amount", 0)),
            "angle": _extract_angle_from_name(r.get("ad_name", "")),
        }
        for r in top_creatives
    ]

    # Count active/killed campaigns
    active_count = len([r for r in reports if float(r.get("stat_cost", 0)) > 0])
    killed_count = 0  # TODO: track from optimizer actions

    return {
        "date": date_str,
        "total_spend": total_spend,
        "total_gmv": total_gmv,
        "total_orders": total_orders,
        "total_conversions": total_conversions,
        "overall_roi": overall_roi,
        "avg_cpa": avg_cpa,
        "top_creatives": top_creative_list,
        "active_campaigns": active_count,
        "killed_today": killed_count,
        "scaled_today": 0,
        "creatives_produced": 0,  # Populated by scheduler
    }


def _extract_angle_from_name(name: str) -> str:
    """Extract creative angle from campaign name.

    Campaign names follow pattern: yipin_{product}_{angle}_{id}
    """
    parts = name.split("_")
    if len(parts) >= 3:
        return parts[2]
    return ""
