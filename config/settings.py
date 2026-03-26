from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI Services - OpenRouter (OpenAI-compatible gateway)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "deepseek/deepseek-chat"  # DeepSeek V3, 中文优秀且无地区限制

    # TTS - MiniMax
    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_tts_voice: str = "male-qn-qingse"  # 清澈男声, good for food ads
    minimax_tts_url: str = "https://api.minimax.chat/v1/t2a_v2"

    # Legacy (kept for backward compat in tests)
    anthropic_api_key: str = ""

    # 巨量千川
    qianchuan_app_id: str = ""
    qianchuan_app_secret: str = ""
    qianchuan_advertiser_id: str = ""
    qianchuan_access_token: str = ""
    qianchuan_base_url: str = "https://ad.oceanengine.com/open_api"

    # 抖店
    doudian_app_key: str = ""
    doudian_app_secret: str = ""
    doudian_shop_id: str = ""
    doudian_base_url: str = "https://openapi-fxg.jinritemai.com"

    # 飞书
    feishu_webhook_url: str = ""

    # Database
    database_url: str = "sqlite:///yipin.db"
    redis_url: str = "redis://localhost:6379/0"

    # Business rules
    max_budget_per_campaign: int = 500
    target_cpa: float = 25.0
    stop_loss_threshold: float = 200.0
    scale_up_ratio: float = 1.5       # ROI good → budget × 1.5
    kill_cpa_ratio: float = 1.5       # CPA > target × 1.5 → kill
    min_spend_before_kill: float = 200.0  # spend this much before judging

    # Creative generation
    daily_creatives_count: int = 20
    videos_per_product: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
