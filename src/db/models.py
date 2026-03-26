from __future__ import annotations

"""Database models - persistent state for 24/7 operation.

All in-memory state moves here: campaigns, creatives, orders, job runs.
"""

from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Text, Boolean, JSON,
    ForeignKey, create_engine, Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from config.settings import settings

Base = declarative_base()


# ---- Multi-tenant tables ----

class Merchant(Base):
    """Merchant (商家) record."""
    __tablename__ = "merchants"

    id = Column(String(32), primary_key=True)
    name = Column(String(128), nullable=False)
    contact_name = Column(String(64), default="")
    contact_phone = Column(String(32), default="")
    status = Column(String(16), default="pending")  # pending|active|paused
    feishu_webhook_url = Column(String(512), default="")
    commission_rate = Column(Float, default=0.10)  # 10% default
    created_at = Column(DateTime, default=datetime.utcnow)

    credentials = relationship("MerchantCredential", back_populates="merchant")
    products = relationship("MerchantProduct", back_populates="merchant")


class MerchantCredential(Base):
    """Per-merchant platform credentials (千川/抖店 OAuth tokens)."""
    __tablename__ = "merchant_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=False, index=True)
    platform = Column(String(32), nullable=False)  # qianchuan|doudian
    app_id = Column(String(64), default="")
    app_secret = Column(String(128), default="")
    advertiser_id = Column(String(64), default="")
    access_token = Column(Text, default="")
    refresh_token = Column(Text, default="")
    expires_at = Column(DateTime, nullable=True)
    shop_id = Column(String(64), default="")
    updated_at = Column(DateTime, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="credentials")

    __table_args__ = (
        Index("ix_merchant_cred_platform", "merchant_id", "platform"),
    )


class MerchantProduct(Base):
    """Per-merchant product configuration (replaces products.yaml for tenants)."""
    __tablename__ = "merchant_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=False, index=True)
    product_key = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    short_name = Column(String(64), default="")
    price = Column(Float, default=0)
    cost = Column(Float, default=0)
    target_cpa = Column(Float, default=25.0)
    selling_points = Column(JSON, default=list)
    pain_points = Column(JSON, default=list)
    hooks = Column(JSON, default=list)
    hashtags = Column(JSON, default=list)
    images_dir = Column(String(512), default="")
    doudian_product_id = Column(String(64), default="")
    supplier_config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="products")

    __table_args__ = (
        Index("ix_merchant_product_key", "merchant_id", "product_key", unique=True),
    )


class BillingRecord(Base):
    """Billing/settlement record per merchant per period."""
    __tablename__ = "billing_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=False, index=True)
    period = Column(String(16), nullable=False)  # e.g. "2026-03" or "2026-W13"
    total_spend = Column(Float, default=0)
    total_gmv = Column(Float, default=0)
    total_orders = Column(Integer, default=0)
    commission_rate = Column(Float, default=0)
    commission_amount = Column(Float, default=0)
    status = Column(String(16), default="draft")  # draft|confirmed|paid
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_billing_merchant_period", "merchant_id", "period"),
    )


# ---- Existing tables (now with optional merchant_id) ----

class Creative(Base):
    """Generated ad creative record."""
    __tablename__ = "creatives"

    id = Column(String(32), primary_key=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=True, index=True)
    batch_id = Column(String(16), index=True)
    product_key = Column(String(64), index=True)
    product_name = Column(String(128))
    angle = Column(String(64))
    hook = Column(Text)
    script_json = Column(JSON)
    video_path = Column(String(512))
    audio_path = Column(String(512))
    duration = Column(Float, default=0)
    status = Column(String(16), default="ready")  # ready|uploaded|active|killed
    created_at = Column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    """Ad campaign record linked to a creative."""
    __tablename__ = "campaigns"

    ad_id = Column(String(64), primary_key=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=True, index=True)
    creative_id = Column(String(32), index=True)
    product_key = Column(String(64), index=True)
    video_id = Column(String(64))
    budget = Column(Float, default=100)
    target_cpa = Column(Float, default=25)
    angle = Column(String(64))
    hook = Column(Text)
    status = Column(String(16), default="active")  # active|paused|killed|completed
    total_spend = Column(Float, default=0)
    total_conversions = Column(Integer, default=0)
    total_gmv = Column(Float, default=0)
    best_roi = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    killed_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_campaign_status", "status"),)


class Order(Base):
    """Order tracking record."""
    __tablename__ = "orders"

    order_id = Column(String(64), primary_key=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=True, index=True)
    product_key = Column(String(64))
    status = Column(String(16), default="new")  # new|relayed|shipped|completed|refunded
    supplier_name = Column(String(128))
    relay_method = Column(String(16))  # feishu|api
    tracking_no = Column(String(64), nullable=True)
    logistics_code = Column(String(32), nullable=True)
    amount = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    shipped_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_order_status", "status"),)


class JobRun(Base):
    """Scheduler job execution record - prevents duplicate runs on restart."""
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(32), ForeignKey("merchants.id"), nullable=True, index=True)
    job_name = Column(String(64), index=True)
    run_date = Column(String(10))  # YYYY-MM-DD
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    result_summary = Column(Text, nullable=True)
    success = Column(Boolean, default=True)


class TokenStore(Base):
    """OAuth token persistent storage - survives restarts."""
    __tablename__ = "tokens"

    platform = Column(String(32), primary_key=True)  # qianchuan|doudian
    access_token = Column(Text)
    refresh_token = Column(Text)
    expires_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow)


# ---- Engine / Session factory ----

# Use sync engine for simplicity (async can be added later)
_sync_url = settings.database_url.replace("+asyncpg", "")
if _sync_url.startswith("postgresql"):
    _sync_url = _sync_url.replace("postgresql", "postgresql+psycopg2", 1) if "+asyncpg" not in settings.database_url else _sync_url


def get_engine(url: str | None = None):
    """Create database engine. Falls back to SQLite for easy local dev."""
    db_url = url or settings.database_url
    if not db_url or "localhost" in db_url:
        db_url = "sqlite:///yipin.db"
    else:
        db_url = db_url.replace("+asyncpg", "")
    return create_engine(db_url, echo=False)


def init_db(url: str | None = None):
    """Create all tables."""
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None):
    """Get a new database session."""
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
