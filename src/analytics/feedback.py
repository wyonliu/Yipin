from __future__ import annotations

"""Feedback loop - analyzes top-performing creatives and extracts patterns."""

import logging

import httpx

from config.settings import settings
from src.adops.optimizer import get_top_performing_creatives
from src.common.retry import with_retry, safe_json_parse

logger = logging.getLogger(__name__)


@with_retry(max_retries=2, base_delay=3.0, exceptions=(httpx.HTTPError, RuntimeError))
async def analyze_creative_performance(days: int = 7) -> dict:
    """Analyze recent creative performance and extract winning patterns."""
    top_creatives = await get_top_performing_creatives(days=days, limit=10)

    if len(top_creatives) < 2:
        return {"insights": [], "recommended_angles": [], "recommended_hooks": []}

    creative_data = "\n".join(
        f"- Ad {c['ad_id']}: ROI={c['roi']:.1f}, CPA=¥{c['cpa']:.0f}, "
        f"Angle={c.get('angle', '?')}, Hook={c.get('hook_style', '?')}"
        for c in top_creatives
    )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.openrouter_model,
        "max_tokens": 1024,
        "messages": [{
            "role": "user",
            "content": f"""分析以下千川投流素材的表现数据，提取成功模式：

{creative_data}

请直接返回JSON对象：
{{
  "insights": ["洞察1", "洞察2"],
  "recommended_angles": ["建议加大的角度"],
  "avoid_angles": ["建议减少的角度"],
  "recommended_hooks": ["建议的钩子风格"],
  "budget_suggestion": "整体预算建议"
}}"""
        }],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()

    text = result["choices"][0]["message"]["content"]
    parsed = safe_json_parse(text, expect_type="object")
    if parsed is None:
        logger.warning("Failed to parse feedback analysis, returning empty")
        return {"insights": [], "recommended_angles": [], "recommended_hooks": []}

    return parsed
