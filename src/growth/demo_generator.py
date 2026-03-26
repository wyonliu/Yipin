from __future__ import annotations

"""Free demo generator — the growth hook.

Merchant enters product name + selling points → AI instantly generates
sample scripts + optional audio preview. No OAuth required.
This is the "try before you buy" that converts merchants into customers.
"""

import logging

import httpx

from config.settings import settings
from src.common.retry import safe_json_parse

logger = logging.getLogger(__name__)


async def generate_demo_scripts(
    product_name: str,
    selling_points: list[str],
    price: float | None = None,
    category: str = "食品",
) -> list[dict]:
    """Generate 3 sample ad scripts for a merchant's product.

    This is FREE — no OAuth, no signup needed. Pure lead magnet.

    Returns:
        List of script dicts with hook, body, cta, full_script, angle
    """
    points_text = "、".join(selling_points) if selling_points else "品质好"
    price_text = f"售价{price}元" if price else ""

    prompt = f"""你是一个顶级抖音带货文案师。为以下产品生成3条短视频带货脚本。

产品：{product_name}
类目：{category}
卖点：{points_text}
{price_text}

要求：
- 每条15-20秒，口语化，有感染力
- 3条脚本角度完全不同（如：痛点型、种草型、场景型）
- 每条包含：开头钩子(3秒内抓住注意力) + 正文 + 行动号召
- 返回JSON数组，每个元素：{{"hook":"...","body":"...","cta":"...","full_script":"完整脚本","angle":"角度名"}}
- 只返回JSON，不要其他文字"""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openrouter_model.strip(),
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()

    text = result["choices"][0]["message"]["content"]
    scripts = safe_json_parse(text, expect_type="array")
    if scripts:
        return scripts[:3]

    return []


async def generate_demo_audio(text: str) -> bytes | None:
    """Generate a short TTS audio preview for one script.

    Returns raw MP3 bytes or None on failure.
    """
    if not settings.minimax_api_key:
        return None

    payload = {
        "model": "speech-01-turbo",
        "text": text[:200],  # Cap length for demo
        "stream": False,
        "voice_setting": {
            "voice_id": settings.minimax_tts_voice,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }

    try:
        url = settings.minimax_tts_url
        if settings.minimax_group_id:
            url += f"?GroupId={settings.minimax_group_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        audio_hex = data.get("data", {}).get("audio", "")
        if audio_hex:
            return bytes.fromhex(audio_hex)
    except Exception as e:
        logger.error(f"Demo audio generation failed: {e}")

    return None
