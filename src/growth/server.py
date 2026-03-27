from __future__ import annotations

"""FastAPI server — landing page + free demo + merchant onboarding.

Endpoints:
  GET  /                     Landing page (serves static HTML)
  POST /api/demo/scripts     Free demo: generate sample scripts
  POST /api/demo/audio       Free demo: generate audio preview
  POST /api/merchant/register  Register new merchant
  GET  /api/merchant/oauth-url Get OAuth redirect URL
  GET  /oauth/callback       千川 OAuth callback
  GET  /api/health           Health check
"""

import base64
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="邑品引擎 - AI千川代投平台", version="0.2.0")

STATIC_DIR = Path(__file__).parent / "static"

# Vercel serverless: use /tmp for writable SQLite
if os.environ.get("VERCEL"):
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/yipin.db")


@app.on_event("startup")
async def startup():
    from src.db.models import init_db
    init_db()


# ---- Landing Page ----

@app.get("/", response_class=HTMLResponse)
async def landing_page():
    """Serve the landing page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>邑品引擎 — AI千川代投平台</h1><p>Coming soon</p>")


# ---- Free Demo API ----

@app.post("/api/demo/scripts")
async def demo_scripts(request: Request):
    """Free demo: generate 3 sample ad scripts for any product."""
    from src.growth.demo_generator import generate_demo_scripts

    body = await request.json()
    product_name = body.get("product_name", "")
    selling_points = body.get("selling_points", [])
    price = body.get("price")
    category = body.get("category", "食品")

    if not product_name:
        return JSONResponse({"error": "product_name is required"}, status_code=400)

    try:
        scripts = await generate_demo_scripts(
            product_name=product_name,
            selling_points=selling_points,
            price=price,
            category=category,
        )
        return {"scripts": scripts, "count": len(scripts)}
    except Exception as e:
        return JSONResponse({"error": str(e), "type": type(e).__name__}, status_code=500)


@app.post("/api/demo/audio")
async def demo_audio(request: Request):
    """Free demo: generate audio preview for a script."""
    from src.growth.demo_generator import generate_demo_audio

    body = await request.json()
    text = body.get("text", "")
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    audio_bytes = await generate_demo_audio(text)
    if audio_bytes:
        audio_b64 = base64.b64encode(audio_bytes).decode()
        return {"audio_base64": audio_b64, "format": "mp3"}
    return JSONResponse({"error": "audio generation failed"}, status_code=500)


# ---- Merchant Onboarding ----

@app.post("/api/merchant/register")
async def merchant_register(request: Request):
    """Register a new merchant."""
    from src.growth.onboarding import register_merchant

    body = await request.json()
    result = register_merchant(
        name=body.get("name", ""),
        contact_name=body.get("contact_name", ""),
        contact_phone=body.get("contact_phone", ""),
        product_info=body.get("product"),
    )
    return result


@app.get("/api/merchant/oauth-url")
async def merchant_oauth_url(merchant_id: str):
    """Get the 千川 OAuth URL for a merchant to authorize."""
    from src.growth.onboarding import get_oauth_url

    url = get_oauth_url(merchant_id)
    return {"oauth_url": url, "merchant_id": merchant_id}


@app.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = ""):
    """千川 OAuth callback — exchange code for token, activate merchant."""
    from src.growth.onboarding import handle_oauth_callback

    if not code or not state:
        return JSONResponse({"error": "missing code or state"}, status_code=400)

    try:
        result = await handle_oauth_callback(auth_code=code, merchant_id=state)
        # Redirect to success page
        return RedirectResponse(url=f"/?onboarded=1&merchant_id={state}")
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ---- SEO Articles ----

@app.get("/articles", response_class=HTMLResponse)
async def articles_index():
    """List all SEO articles."""
    import json
    idx_path = STATIC_DIR / "seo" / "index.json"
    if not idx_path.exists():
        return HTMLResponse("<h1>文章列表</h1><p>暂无文章</p>")
    articles = json.loads(idx_path.read_text(encoding="utf-8"))
    links = "".join(
        f'<li><a href="/articles/{a["slug"]}">{a["title"]}</a></li>'
        for a in articles
    )
    return HTMLResponse(f"""<!DOCTYPE html><html lang="zh"><head>
<meta charset="utf-8"><title>千川投流干货 - 邑品引擎</title>
<style>body{{font-family:system-ui;max-width:800px;margin:0 auto;padding:20px;background:#0a0a16;color:#e0e0e0}}
a{{color:#c8a96e}}h1{{color:#c8a96e}}</style>
</head><body><h1>千川投流干货文章</h1><ul>{links}</ul>
<p><a href="/">← 返回首页</a></p></body></html>""")


@app.get("/articles/{slug}", response_class=HTMLResponse)
async def article_page(slug: str):
    """Serve an individual SEO article."""
    html_path = STATIC_DIR / "seo" / f"{slug}.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return JSONResponse({"error": "article not found"}, status_code=404)


# ---- Merchant Dashboard API ----

@app.get("/api/merchant/{merchant_id}/status")
async def merchant_status(merchant_id: str):
    """Get merchant status and stats."""
    from src.common.tenant import get_merchant, get_merchant_products
    merchant = get_merchant(merchant_id)
    if not merchant:
        return JSONResponse({"error": "merchant not found"}, status_code=404)
    products = get_merchant_products(merchant_id)
    return {
        "merchant_id": merchant.id,
        "name": merchant.name,
        "status": merchant.status,
        "products": len(products),
        "created_at": str(merchant.created_at),
    }


@app.get("/api/merchants")
async def list_merchants():
    """List all merchants (admin view)."""
    from src.db.models import get_session, Merchant
    with get_session() as session:
        merchants = session.query(Merchant).all()
        return {
            "merchants": [
                {
                    "id": m.id,
                    "name": m.name,
                    "status": m.status,
                    "created_at": str(m.created_at),
                }
                for m in merchants
            ],
            "total": len(merchants),
        }


# ---- Health ----

@app.get("/api/health")
async def health():
    from config.settings import settings
    return {
        "status": "ok",
        "service": "yipin-engine",
        "has_openrouter_key": bool(settings.openrouter_api_key),
        "model": settings.openrouter_model,
        "db_url": settings.database_url[:30],
    }
