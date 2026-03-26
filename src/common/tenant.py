from __future__ import annotations

"""Multi-tenant context utilities.

Resolves merchant-specific data (credentials, products) from DB.
Falls back to global settings when merchant_id is None (backward compat).
"""

import logging
from datetime import datetime

from config.settings import settings
from src.db.models import (
    get_session, Merchant, MerchantCredential, MerchantProduct,
)

logger = logging.getLogger(__name__)


def get_merchant(merchant_id: str) -> Merchant | None:
    """Get a merchant by ID."""
    session = get_session()
    try:
        return session.query(Merchant).filter_by(id=merchant_id).first()
    finally:
        session.close()


def get_all_active_merchants() -> list[Merchant]:
    """Get all merchants with status='active'."""
    session = get_session()
    try:
        return session.query(Merchant).filter_by(status="active").all()
    finally:
        session.close()


def get_merchant_credentials(merchant_id: str, platform: str) -> dict:
    """Get credentials for a merchant+platform.

    Returns dict with: app_id, app_secret, advertiser_id, access_token,
    refresh_token, shop_id, expires_at.

    Falls back to global settings if no DB record found.
    """
    session = get_session()
    try:
        cred = (
            session.query(MerchantCredential)
            .filter_by(merchant_id=merchant_id, platform=platform)
            .first()
        )
        if cred:
            return {
                "app_id": cred.app_id or "",
                "app_secret": cred.app_secret or "",
                "advertiser_id": cred.advertiser_id or "",
                "access_token": cred.access_token or "",
                "refresh_token": cred.refresh_token or "",
                "shop_id": cred.shop_id or "",
                "expires_at": cred.expires_at,
            }
    finally:
        session.close()

    # Fallback to global settings
    if platform == "qianchuan":
        return {
            "app_id": settings.qianchuan_app_id,
            "app_secret": settings.qianchuan_app_secret,
            "advertiser_id": settings.qianchuan_advertiser_id,
            "access_token": settings.qianchuan_access_token,
            "refresh_token": "",
            "shop_id": "",
            "expires_at": None,
        }
    elif platform == "doudian":
        return {
            "app_id": settings.doudian_app_key,
            "app_secret": settings.doudian_app_secret,
            "advertiser_id": "",
            "access_token": "",
            "refresh_token": "",
            "shop_id": settings.doudian_shop_id,
            "expires_at": None,
        }
    return {}


def get_merchant_products(merchant_id: str) -> dict[str, dict]:
    """Get all active products for a merchant, keyed by product_key.

    Returns same format as load_products() from pipeline.py for compatibility.
    """
    session = get_session()
    try:
        products = (
            session.query(MerchantProduct)
            .filter_by(merchant_id=merchant_id, is_active=True)
            .all()
        )
        return {
            p.product_key: {
                "name": p.name,
                "short_name": p.short_name,
                "price": p.price,
                "cost": p.cost,
                "target_cpa": p.target_cpa,
                "selling_points": p.selling_points or [],
                "pain_points": p.pain_points or [],
                "hooks": p.hooks or [],
                "hashtags": p.hashtags or [],
                "images_dir": p.images_dir,
                "doudian_product_id": p.doudian_product_id,
                "supplier": p.supplier_config or {},
            }
            for p in products
        }
    finally:
        session.close()


def save_merchant_token(merchant_id: str, platform: str, token_data: dict) -> None:
    """Update access/refresh token for a merchant credential."""
    session = get_session()
    try:
        cred = (
            session.query(MerchantCredential)
            .filter_by(merchant_id=merchant_id, platform=platform)
            .first()
        )
        if cred:
            cred.access_token = token_data.get("access_token", cred.access_token)
            cred.refresh_token = token_data.get("refresh_token", cred.refresh_token)
            if "expires_at" in token_data:
                cred.expires_at = token_data["expires_at"]
            cred.updated_at = datetime.utcnow()
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
