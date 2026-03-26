from __future__ import annotations

"""SEO content auto-generator.

Generates articles targeting merchant pain point keywords like:
- "千川投流效果差怎么办"
- "千川代投哪家好"
- "抖店投流自动化"

Each article naturally funnels to the free demo tool.
"""

import logging

import httpx

from config.settings import settings
from src.common.retry import safe_json_parse

logger = logging.getLogger(__name__)

# Target keywords that merchants search for
SEED_KEYWORDS = [
    "千川投流效果差怎么办",
    "千川代投收费标准",
    "抖店千川怎么投效果好",
    "千川素材制作成本太高",
    "千川投流自动化工具",
    "AI千川投流",
    "千川短视频素材批量制作",
    "千川ROI太低怎么优化",
    "千川投手太贵请不起",
    "抖店怎么提高千川转化率",
]


async def generate_seo_article(keyword: str) -> dict | None:
    """Generate a 1500-word SEO article targeting a specific keyword.

    Returns dict with: title, meta_description, body_html, keyword
    """
    prompt = f"""你是一个精通抖音电商和千川投流的内容营销专家。

请写一篇面向抖店商家的SEO文章，核心关键词：「{keyword}」

要求：
1. 标题包含关键词，吸引点击
2. 正文1500字左右，自然植入关键词5-8次
3. 内容真正有价值：分析痛点原因、给出可操作建议
4. 在文末自然引出「AI自动化投流」解决方案（不要硬广）
5. 包含一个行动号召：试用免费AI脚本生成工具

返回JSON格式：
{{"title":"...","meta_description":"50字SEO描述","body_html":"<p>正文HTML</p>","keyword":"{keyword}"}}

只返回JSON。"""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openrouter_model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()

        text = result["choices"][0]["message"]["content"]
        article = safe_json_parse(text, expect_type="object")
        return article
    except Exception as e:
        logger.error(f"SEO article generation failed for '{keyword}': {e}")
        return None


async def generate_all_seed_articles() -> list[dict]:
    """Generate articles for all seed keywords. Call once at setup."""
    articles = []
    for kw in SEED_KEYWORDS:
        article = await generate_seo_article(kw)
        if article:
            articles.append(article)
            logger.info(f"Generated SEO article: {article.get('title', kw)}")
    return articles
