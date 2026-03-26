from __future__ import annotations

"""Merchant self-service onboarding.

Flow:
1. Merchant fills form (name, contact, product info)
2. AI generates free demo scripts (instant gratification)
3. Merchant clicks "开通服务" → OAuth redirect to 千川
4. OAuth callback → save credentials → activate merchant → auto-start
"""

import logging
import uuid
from datetime import datetime, timedelta

import httpx

from config.settings import settings
from src.db.models import (
    get_session, Merchant, MerchantCredential, MerchantProduct,
)

logger = logging.getLogger(__name__)


def register_merchant(
    name: str,
    contact_name: str,
    contact_phone: str,
    product_info: dict | None = None,
) -> dict:
    """Step 1: Register a new merchant (pending status).

    Returns merchant_id for subsequent steps.
    """
    merchant_id = uuid.uuid4().hex[:12]

    session = get_session()
    try:
        merchant = Merchant(
            id=merchant_id,
            name=name,
            contact_name=contact_name,
            contact_phone=contact_phone,
            status="pending",
            commission_rate=0.10,
            created_at=datetime.utcnow(),
        )
        session.add(merchant)

        # If product info provided, save it
        if product_info:
            product_key = product_info.get("product_key") or f"prod_{merchant_id[:6]}"
            mp = MerchantProduct(
                merchant_id=merchant_id,
                product_key=product_key,
                name=product_info.get("name", ""),
                short_name=product_info.get("short_name", ""),
                price=product_info.get("price", 0),
                selling_points=product_info.get("selling_points", []),
                pain_points=product_info.get("pain_points", []),
                hooks=product_info.get("hooks", []),
                images_dir=product_info.get("images_dir", ""),
                doudian_product_id=product_info.get("doudian_product_id", ""),
                supplier_config=product_info.get("supplier", {}),
                is_active=True,
            )
            session.add(mp)

        session.commit()
        logger.info(f"Merchant registered: {merchant_id} ({name})")
        return {"merchant_id": merchant_id, "status": "pending"}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_oauth_url(merchant_id: str) -> str:
    """Step 3: Generate 千川 OAuth authorization URL.

    Merchant clicks this → authorizes on 千川 → redirects back with auth code.
    """
    # 千川 OAuth2 authorize endpoint
    base = "https://qianchuan.jinritemai.com/openapi/qc/audit/oauth.html"
    params = {
        "app_id": settings.qianchuan_app_id,
        "state": merchant_id,  # Pass merchant_id through OAuth state
        "redirect_uri": f"{settings.openrouter_base_url.replace('/api/v1', '')}/oauth/callback",
        # In production, this should be your actual callback URL
        # For now, use a placeholder that will be configured at deploy time
    }
    # Build URL
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}?{query}"


async def handle_oauth_callback(auth_code: str, merchant_id: str) -> dict:
    """Step 4: Exchange auth code for access token, save to DB, activate merchant.

    Called by the OAuth callback endpoint.
    """
    # Exchange auth code for tokens
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.qianchuan_base_url}/oauth2/access_token/",
            json={
                "app_id": settings.qianchuan_app_id,
                "secret": settings.qianchuan_app_secret,
                "code": auth_code,
                "grant_type": "auth_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()["data"]

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    expires_in = data.get("expires_in", 86400)  # Default 24h
    advertiser_ids = data.get("advertiser_ids", [])
    advertiser_id = str(advertiser_ids[0]) if advertiser_ids else ""

    # Save credentials to DB
    session = get_session()
    try:
        cred = MerchantCredential(
            merchant_id=merchant_id,
            platform="qianchuan",
            app_id=settings.qianchuan_app_id,
            app_secret=settings.qianchuan_app_secret,
            advertiser_id=advertiser_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
        )
        session.add(cred)

        # Activate merchant
        merchant = session.query(Merchant).filter_by(id=merchant_id).first()
        if merchant:
            merchant.status = "active"

        session.commit()
        logger.info(f"Merchant {merchant_id} OAuth complete, activated")
        return {
            "merchant_id": merchant_id,
            "advertiser_id": advertiser_id,
            "status": "active",
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
