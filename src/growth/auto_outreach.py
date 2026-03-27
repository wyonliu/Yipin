"""Automated merchant outreach engine.

Channels:
  1. SEO articles (already generated, served via /articles)
  2. Knowledge platform Q&A (知乎-style answers)
  3. Social media posts (小红书/抖音文案)
  4. Direct outreach templates (for future webhook/email integration)

All content funnels to https://yipin.vercel.app
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from config.settings import settings
from src.common.retry import safe_json_parse

logger = logging.getLogger(__name__)

SITE_URL = "https://yipin.vercel.app"


async def generate_zhihu_answers(count: int = 5) -> list[dict]:
    """Generate Q&A style content targeting merchant pain points."""
    prompt = f"""你是一个千川投流老手，在知乎/百度知道上回答商家问题。

请生成{count}组问答，每组包含：
1. question: 商家会搜索的问题（自然语言）
2. answer: 专业、有价值的回答（300-500字），最后自然引出AI自动投流工具（不硬广）
3. tags: 相关标签3-5个

目标用户：抖店商家，月投放1-10万，被千川素材和ROI困扰。

返回JSON数组。只返回JSON。"""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openrouter_model.strip(),
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
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
    answers = safe_json_parse(text, expect_type="array")
    return answers or []


async def generate_social_posts(count: int = 10) -> list[dict]:
    """Generate social media posts for 小红书/抖音/微信 distribution."""
    prompt = f"""你是一个抖音电商领域的小红书博主，要发布引流帖子吸引抖店商家。

请生成{count}条社交媒体帖子，每条包含：
1. platform: "xiaohongshu" 或 "douyin" 或 "weixin"
2. title: 吸引点击的标题（20字内）
3. body: 正文内容（小红书150-300字，抖音评论区50字）
4. hashtags: 相关话题标签5-8个
5. hook_type: "数据对比" / "踩坑经验" / "工具推荐" / "行业内幕"

核心信息：AI千川投流工具，免费试用，自动生成素材，按效果付费。
站点：{SITE_URL}

返回JSON数组。只返回JSON。"""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openrouter_model.strip(),
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
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
    posts = safe_json_parse(text, expect_type="array")
    return posts or []


async def generate_outreach_batch() -> dict:
    """Generate a full batch of outreach content across all channels."""
    logger.info("Generating outreach content batch...")

    qa = await generate_zhihu_answers(5)
    posts = await generate_social_posts(10)

    # Save to disk for review/distribution
    output_dir = Path(__file__).parent / "static" / "outreach"
    output_dir.mkdir(parents=True, exist_ok=True)

    batch = {
        "zhihu_answers": qa,
        "social_posts": posts,
        "total_pieces": len(qa) + len(posts),
    }

    (output_dir / "latest_batch.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"Generated {batch['total_pieces']} outreach pieces")
    return batch
