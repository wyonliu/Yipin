from __future__ import annotations

"""Startup validation - checks all prerequisites before the engine runs."""

import logging
import shutil
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


class StartupError(Exception):
    """Raised when a critical prerequisite is missing."""
    pass


def validate_all() -> list[str]:
    """Run all startup checks. Returns list of warnings (non-fatal).
    Raises StartupError for fatal issues.
    """
    warnings = []

    # ---- Fatal checks ----

    if not settings.openrouter_api_key:
        raise StartupError("OPENROUTER_API_KEY is required (drives creative generation)")

    if not shutil.which("ffmpeg"):
        raise StartupError("ffmpeg not found in PATH. Install: brew install ffmpeg")

    if not shutil.which("ffprobe"):
        raise StartupError("ffprobe not found in PATH. Install: brew install ffmpeg")

    # ---- Non-fatal warnings ----

    if not settings.minimax_api_key:
        warnings.append("MiniMax TTS not configured - voice generation will fail")

    if not settings.qianchuan_app_id or not settings.qianchuan_app_secret:
        warnings.append("Qianchuan API not configured - ad operations will fail")

    if not settings.doudian_app_key or not settings.doudian_app_secret:
        warnings.append("Doudian API not configured - order fulfillment will fail")

    if not settings.feishu_webhook_url:
        warnings.append("Feishu webhook not configured - notifications disabled")

    # Check product images
    products_yaml = Path("config/products.yaml")
    if not products_yaml.exists():
        warnings.append("config/products.yaml not found")

    # Check workspace directory
    Path("workspace/creatives").mkdir(parents=True, exist_ok=True)

    # Check assets
    bgm_dir = Path("assets/bgm")
    if not bgm_dir.exists() or not list(bgm_dir.glob("*.mp3")):
        warnings.append("No BGM files in assets/bgm/ - videos will have no background music")

    fonts_dir = Path("assets/fonts")
    if not fonts_dir.exists() or not list(fonts_dir.glob("*.ttf")):
        warnings.append("No font files in assets/fonts/ - text cards will use default font")

    return warnings


def print_startup_banner(warnings: list[str]) -> None:
    """Print a startup banner with system status."""
    logger.info("=" * 60)
    logger.info("  邑品引擎 v0.1.0 - AI Automated Commerce Engine")
    logger.info("=" * 60)

    checks = {
        "OpenRouter LLM": bool(settings.openrouter_api_key),
        "MiniMax TTS": bool(settings.minimax_api_key),
        "千川投放": bool(settings.qianchuan_app_id),
        "抖店履约": bool(settings.doudian_app_key),
        "飞书通知": bool(settings.feishu_webhook_url),
        "FFmpeg": bool(shutil.which("ffmpeg")),
    }

    for name, ok in checks.items():
        status = "✓" if ok else "✗"
        logger.info(f"  [{status}] {name}")

    if warnings:
        logger.info("")
        logger.info("  Warnings:")
        for w in warnings:
            logger.warning(f"    ⚠ {w}")

    logger.info("=" * 60)
