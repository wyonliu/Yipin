#!/usr/bin/env python3
"""干跑测试 - 只用 OpenRouter API 验证素材生成流程。

这是你拿到 OpenRouter API key 后第一个该跑的测试。
验证: LLM 脚本生成 → 输出质量检查

Usage: python3 scripts/test_pipeline_dry_run.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


SAMPLE_PRODUCT = {
    "name": "葛根茯苓酥",
    "short_name": "葛根酥",
    "origin": "洛阳",
    "heritage_tag": "河南非遗传统糕点",
    "price": 59.0,
    "selling_points": [
        "传承200年的洛阳非遗糕点配方",
        "葛根+茯苓，药食同源，健康零食",
        "不添加防腐剂，手工现做现发",
        "入口即化，不甜不腻，老少皆宜",
    ],
    "pain_points": [
        "送礼不知道送什么，千篇一律没新意",
        "想吃零食又怕不健康",
        "河南美食这么多，可惜很多人不知道",
    ],
    "hooks": [
        "你知道河南有一种吃了200年的糕点吗？",
        "办公室零食别再吃垃圾食品了！",
        "葛根茯苓是什么？老中医自己都在吃",
        "送爸妈的礼物，我终于找到了",
        "药店里葛根茯苓片卖200，这个才59",
        "在外地的河南人，看到这个可能会哭",
        "同事抢着问我这零食哪买的",
        "下午三点犯困，我掏出了这个",
    ],
}


async def main():
    from config.settings import settings

    if not settings.openrouter_api_key:
        print("❌ 请先在 .env 中设置 OPENROUTER_API_KEY")
        print("   获取地址: https://openrouter.ai/settings/keys")
        sys.exit(1)

    print("=" * 60)
    print("  邑品引擎 - 素材生成干跑测试")
    print(f"  模型: {settings.openrouter_model}")
    print("=" * 60)
    print()

    # Test 1: Script generation
    print("📝 测试1: LLM 脚本生成 (5条)...")
    from src.creative.scriptwriter import generate_scripts

    scripts = await generate_scripts(SAMPLE_PRODUCT, count=5)

    if not scripts:
        print("❌ 脚本生成失败！检查 API key 是否正确")
        sys.exit(1)

    print(f"✅ 成功生成 {len(scripts)} 条脚本\n")

    # Quality check
    angles_seen = set()
    hooks_seen = set()
    all_good = True

    for i, script in enumerate(scripts):
        print(f"--- 脚本 {i+1} ---")
        print(f"  角度: {script.get('angle', '❌ 缺失')}")
        print(f"  钩子: {script.get('hook', '❌ 缺失')}")
        print(f"  时长: {script.get('estimated_duration', '?')}秒")
        print(f"  字幕段: {len(script.get('subtitle_segments', []))}段")
        print(f"  完整文案: {script.get('full_script', '')[:60]}...")
        print()

        angle = script.get("angle", "")
        hook = script.get("hook", "")

        if angle in angles_seen:
            print(f"  ⚠️ 角度重复: {angle}")
            all_good = False
        angles_seen.add(angle)

        if hook[:10] in [h[:10] for h in hooks_seen]:
            print(f"  ⚠️ 钩子句式雷同")
            all_good = False
        hooks_seen.add(hook)

        if not script.get("full_script"):
            print(f"  ❌ 缺少完整文案")
            all_good = False

        if not script.get("subtitle_segments"):
            print(f"  ❌ 缺少字幕分段")
            all_good = False

    print("=" * 60)
    if all_good:
        print("✅ 所有脚本质量检查通过！")
        print()
        print("下一步:")
        print("  1. 测试 MiniMax TTS 配音")
        print("  2. 准备产品图片 → 测试完整视频合成")
        print("  3. python3 main.py creatives  # 完整素材生产流水线")
    else:
        print("⚠️ 部分脚本存在质量问题，可能需要调整 prompt")
        print("  可以修改 src/creative/scriptwriter.py 中的 SYSTEM_PROMPT")

    # Save scripts for review
    output_dir = Path("workspace/dry_run")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "test_scripts.json"
    output_file.write_text(json.dumps(scripts, ensure_ascii=False, indent=2))
    print(f"\n📄 脚本已保存到 {output_file}，可以仔细检查质量")


if __name__ == "__main__":
    asyncio.run(main())
