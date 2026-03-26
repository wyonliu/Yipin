#!/usr/bin/env python3
"""邑品引擎 - 一键配置向导

交互式引导你填写所有 API 密钥，自动写入 .env 文件。
跑完这个脚本，系统就能启动。

Usage: python3 scripts/setup_wizard.py
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".env"
ENV_EXAMPLE = Path(__file__).parent.parent / ".env.example"


def ask(prompt, default="", secret=False):
    """Ask user for input with optional default."""
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default


def main():
    print()
    print("=" * 60)
    print("  邑品引擎 - 配置向导")
    print("  按提示填入各平台的 API 密钥")
    print("  跳过的项目可以后续在 .env 文件中手动填写")
    print("=" * 60)
    print()

    config = {}

    # --- OpenRouter API ---
    print("【1/6】OpenRouter API（AI素材生成引擎）")
    print("  获取地址: https://openrouter.ai/settings/keys")
    config["OPENROUTER_API_KEY"] = ask("API Key (sk-or-v1-...)", secret=True)
    config["OPENROUTER_MODEL"] = ask("Model", default="anthropic/claude-sonnet-4")
    print()

    # --- MiniMax TTS ---
    print("【2/6】MiniMax TTS（AI配音）")
    print("  注册: https://platform.minimaxi.com")
    print("  步骤: 注册→实名认证→获取 API Key")
    config["MINIMAX_API_KEY"] = ask("API Key (sk-api-...)", secret=True)
    config["MINIMAX_GROUP_ID"] = ask("Group ID (可选)")
    config["MINIMAX_TTS_VOICE"] = ask("TTS Voice ID", default="male-qn-qingse")
    print()

    # --- Qianchuan ---
    print("【3/6】巨量千川（广告投放）")
    print("  开发者入驻: https://open.oceanengine.com")
    print("  步骤: 注册→创建应用(选千川)→获取 App ID/Secret→商家授权→获取 Access Token")
    config["QIANCHUAN_APP_ID"] = ask("App ID")
    config["QIANCHUAN_APP_SECRET"] = ask("App Secret", secret=True)
    config["QIANCHUAN_ADVERTISER_ID"] = ask("Advertiser ID (广告主ID)")
    print()

    # --- Doudian ---
    print("【4/6】抖店开放平台（订单履约）")
    print("  开发者入驻: https://op.jinritemai.com")
    print("  步骤: 注册→创建自用型应用→获取 App Key/Secret")
    config["DOUDIAN_APP_KEY"] = ask("App Key")
    config["DOUDIAN_APP_SECRET"] = ask("App Secret", secret=True)
    config["DOUDIAN_SHOP_ID"] = ask("Shop ID (店铺ID)")
    print()

    # --- Feishu ---
    print("【5/6】飞书机器人（通知告警）")
    print("  创建: 飞书群 → 设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook URL")
    config["FEISHU_WEBHOOK_URL"] = ask("Webhook URL")
    print()

    # --- Business Config ---
    print("【6/6】业务参数")
    config["TARGET_CPA"] = ask("目标转化成本(元)", default="25")
    config["MAX_BUDGET_PER_CAMPAIGN"] = ask("单计划最大日预算(元)", default="500")
    config["STOP_LOSS_THRESHOLD"] = ask("止损阈值(元,消耗超此金额且0转化则关停)", default="200")
    print()

    # --- Database ---
    config["DATABASE_URL"] = "sqlite:///yipin.db"

    # Write .env
    lines = []
    for k, v in config.items():
        if v:
            lines.append(f"{k}={v}")
        else:
            lines.append(f"# {k}=  # TODO: fill this")

    ENV_FILE.write_text("\n".join(lines) + "\n")
    print(f"✅ 配置已写入 {ENV_FILE}")
    print()

    # Validate
    missing = [k for k, v in config.items() if not v and k not in ("DATABASE_URL", "MINIMAX_GROUP_ID", "MINIMAX_TTS_VOICE")]
    if missing:
        print(f"⚠️  以下配置暂未填写（可后续补充）:")
        for m in missing:
            print(f"   - {m}")
    else:
        print("🎉 所有配置已就绪！运行以下命令启动:")
        print("   python3 main.py init-db")
        print("   python3 main.py creatives  # 测试素材生成")
        print("   python3 main.py run        # 启动全自动引擎")

    print()


if __name__ == "__main__":
    main()
