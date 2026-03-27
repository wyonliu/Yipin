"""Billing engine — automated commission calculation and collection.

Flow:
  1. AI tracks campaigns with [AI邑品] prefix per merchant
  2. Daily: pull GMV data from 千川 API for each merchant
  3. Calculate commission: GMV × commission_rate (default 10%)
  4. Generate billing record
  5. Send payment link / invoice to merchant via WeChat/飞书

Current stage (MVP): generate billing records + manual WeChat transfer
Next stage: 小微商户 WeChat Pay API integration
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.db.models import get_session, BillingRecord, Merchant

logger = logging.getLogger(__name__)


def calculate_merchant_billing(
    merchant_id: str,
    period: str | None = None,
    total_spend: float = 0,
    total_gmv: float = 0,
    total_orders: int = 0,
) -> dict:
    """Calculate and save billing for a merchant.

    Args:
        merchant_id: Merchant UUID
        period: Billing period string (e.g., '2026-03-W4'). Defaults to current week.
        total_spend: Total ad spend in the period
        total_gmv: Total GMV attributed to AI campaigns
        total_orders: Total orders from AI campaigns
    """
    if not period:
        now = datetime.now()
        period = f"{now.year}-{now.month:02d}-W{(now.day - 1) // 7 + 1}"

    with get_session() as session:
        merchant = session.query(Merchant).filter_by(id=merchant_id).first()
        if not merchant:
            return {"error": "merchant not found"}

        rate = merchant.commission_rate or 0.10
        commission = total_gmv * rate

        # Check for existing record
        existing = (
            session.query(BillingRecord)
            .filter_by(merchant_id=merchant_id, period=period)
            .first()
        )

        if existing:
            existing.total_spend = total_spend
            existing.total_gmv = total_gmv
            existing.total_orders = total_orders
            existing.commission_rate = rate
            existing.commission_amount = commission
            record_id = existing.id
        else:
            record = BillingRecord(
                merchant_id=merchant_id,
                period=period,
                total_spend=total_spend,
                total_gmv=total_gmv,
                total_orders=total_orders,
                commission_rate=rate,
                commission_amount=commission,
                status="draft",
            )
            session.add(record)
            session.flush()
            record_id = record.id

        session.commit()

        merchant_name = merchant.name if merchant else ""

    return {
        "billing_id": record_id,
        "merchant_id": merchant_id,
        "period": period,
        "total_spend": total_spend,
        "total_gmv": total_gmv,
        "total_orders": total_orders,
        "commission_rate": rate,
        "commission_amount": commission,
        "status": "draft",
        "payment_instruction": generate_payment_instruction(
            merchant_name=merchant_name,
            amount=commission,
            period=period,
        ),
    }


def generate_payment_instruction(
    merchant_name: str, amount: float, period: str
) -> str:
    """Generate payment instruction text for the merchant."""
    return (
        f"【邑品引擎 · 账单通知】\n"
        f"商家: {merchant_name}\n"
        f"账期: {period}\n"
        f"应付服务费: ¥{amount:,.2f}\n"
        f"---\n"
        f"转账方式（任选一）:\n"
        f"1. 微信转账至服务号「邑品引擎」\n"
        f"2. 支付宝转账至: yipin@example.com\n"
        f"3. 银行转账至: [对公/对私账户信息]\n"
        f"---\n"
        f"转账备注请写: YP-{period}\n"
        f"收到转账后自动确认，谢谢！"
    )


def get_merchant_billing_summary(merchant_id: str) -> dict:
    """Get billing summary for a merchant."""
    with get_session() as session:
        records = (
            session.query(BillingRecord)
            .filter_by(merchant_id=merchant_id)
            .order_by(BillingRecord.period.desc())
            .all()
        )
        total_commission = sum(r.commission_amount or 0 for r in records)
        total_gmv = sum(r.total_gmv or 0 for r in records)
        total_paid = sum(
            r.commission_amount or 0 for r in records if r.status == "paid"
        )

        return {
            "merchant_id": merchant_id,
            "total_periods": len(records),
            "total_gmv": total_gmv,
            "total_commission": total_commission,
            "total_paid": total_paid,
            "total_outstanding": total_commission - total_paid,
            "records": [
                {
                    "period": r.period,
                    "gmv": r.total_gmv,
                    "commission": r.commission_amount,
                    "status": r.status,
                }
                for r in records
            ],
        }


def simulate_billing_cycle(merchant_id: str) -> dict:
    """Simulate a billing cycle with mock GMV data for testing."""
    import random

    # Simulate weekly performance
    spend = random.uniform(3000, 15000)
    roi = random.uniform(1.5, 4.0)
    gmv = spend * roi
    orders = int(gmv / random.uniform(30, 100))

    result = calculate_merchant_billing(
        merchant_id=merchant_id,
        total_spend=round(spend, 2),
        total_gmv=round(gmv, 2),
        total_orders=orders,
    )
    return result
