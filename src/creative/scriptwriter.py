from __future__ import annotations

"""AI scriptwriter - generates ad scripts using OpenRouter API (OpenAI-compatible)."""

import logging

import httpx

from config.settings import settings
from src.common.retry import with_retry, safe_json_parse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个顶级的短视频带货文案专家，专门为千川投流写高转化脚本。

你的脚本风格：
- 前3秒必须有强钩子（反问/冲突/好奇/痛点）
- 总时长控制在15-25秒（约150-250字）
- 口语化，像朋友推荐，不要播音腔
- 必须包含产品核心卖点
- 结尾有明确行动号召（"点击下方链接"/"赶紧拍一单试试"）
- 不要用"亲""宝宝"等电商黑话

输出格式（严格JSON数组，不要多余文字）：
[
  {
    "hook": "前3秒钩子文案",
    "body": "中间产品介绍文案",
    "cta": "结尾行动号召",
    "full_script": "完整配音文案（一整段，用于TTS）",
    "subtitle_segments": [
      {"text": "字幕片段1", "duration": 3.0},
      {"text": "字幕片段2", "duration": 4.0}
    ],
    "estimated_duration": 20,
    "angle": "素材角度标签(如: 健康养生/送礼场景/价格对比)"
  }
]"""


@with_retry(max_retries=2, base_delay=3.0, exceptions=(httpx.HTTPError, RuntimeError))
async def generate_scripts(
    product: dict,
    count: int = 5,
    top_performers: list[dict] | None = None,
) -> list[dict]:
    """Generate multiple ad scripts for a product via OpenRouter API.

    Args:
        product: Product info dict from products.yaml
        count: Number of scripts to generate
        top_performers: Optional list of top-performing script features to learn from

    Returns:
        List of script dicts. Returns empty list on failure (never crashes).
    """
    feedback_context = ""
    if top_performers:
        feedback_context = "\n\n【历史爆款素材特征，请参考但不要照抄】:\n"
        for p in top_performers[:5]:
            feedback_context += (
                f"- 角度: {p.get('angle', '?')}, 钩子风格: {p.get('hook_style', '?')}, "
                f"转化成本: ¥{p.get('cpa', '?')}, ROI: {p.get('roi', '?')}\n"
            )

    selling_points = product.get("selling_points", [])
    pain_points = product.get("pain_points", [])
    hooks = product.get("hooks", [])

    user_prompt = f"""请为以下产品生成 {count} 条千川投流短视频脚本。

【产品信息】
名称: {product.get('name', '')}
产地: {product.get('origin', '')}
非遗标签: {product.get('heritage_tag', '')}
价格: ¥{product.get('price', '')}

【核心卖点】
{chr(10).join('- ' + sp for sp in selling_points)}

【用户痛点】
{chr(10).join('- ' + pp for pp in pain_points)}

【可选钩子方向】
{chr(10).join('- ' + h for h in hooks)}
{feedback_context}

要求:
1. {count}条脚本的角度必须各不相同（健康养生/送礼场景/办公室零食/非遗文化/价格对比/情感共鸣 等）
2. 每条钩子完全不同，不要重复句式
3. 口语化，真实感，像刷到一个真人在分享好物

请直接返回JSON数组，不要有其他文字。"""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.openrouter_model,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
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
    scripts = safe_json_parse(text, expect_type="array")

    if scripts is None:
        logger.error(f"Failed to parse scripts from LLM response: {text[:300]}")
        return []

    logger.info(f"Generated {len(scripts)} scripts for {product.get('name', '?')}")
    return scripts
