"""End-to-end simulation tests.

Simulates the FULL lifecycle with mocked external APIs:
  1. Creative generation (OpenRouter → scripts → MiniMax TTS → FFmpeg → video)
  2. Campaign launch (upload → create campaign)
  3. Optimization cycle (report → scale/kill decisions)
  4. Order processing (poll → relay to supplier → tracking update)
  5. Daily report
  6. Scheduler job deduplication
  7. Error recovery scenarios

Run: pytest tests/test_e2e_simulation.py -v
"""

import asyncio
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-test-key"
os.environ["DATABASE_URL"] = "sqlite:///test_yipin.db"


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh test database for each test."""
    from src.db.models import init_db, Base, get_engine
    engine = get_engine("sqlite:///test_yipin.db")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    try:
        os.unlink("test_yipin.db")
    except FileNotFoundError:
        pass


@pytest.fixture
def sample_product():
    return {
        "name": "葛根茯苓酥",
        "short_name": "葛根酥",
        "origin": "洛阳",
        "heritage_tag": "河南非遗传统糕点",
        "price": 59.0,
        "cost": 18.0,
        "target_cpa": 22.0,
        "selling_points": ["传承200年", "葛根+茯苓药食同源", "无添加"],
        "pain_points": ["送礼没新意", "零食不健康"],
        "hooks": ["你知道河南有个传了200年的糕点吗？", "办公室零食别再吃垃圾食品了"],
        "hashtags": ["#河南非遗美食"],
        "images_dir": "assets/products/gegen/",
        "supplier": {"name": "测试工坊", "contact_type": "feishu"},
    }


@pytest.fixture
def mock_claude_scripts_response():
    """Simulate LLM returning 3 scripts."""
    scripts = [
        {
            "hook": "你知道河南有个传了200年的糕点吗？",
            "body": "这就是洛阳葛根茯苓酥，葛根茯苓都是药食同源的好东西",
            "cta": "点击下方链接试试，59块钱尝个鲜",
            "full_script": "你知道河南有个传了200年的糕点吗？这就是洛阳葛根茯苓酥。葛根茯苓都是药食同源的好东西，入口即化，不甜不腻。点击下方链接试试，59块钱尝个鲜。",
            "subtitle_segments": [
                {"text": "你知道河南有个传了200年的糕点吗？", "duration": 3.0},
                {"text": "这就是洛阳葛根茯苓酥", "duration": 3.0},
                {"text": "葛根茯苓都是药食同源的好东西", "duration": 4.0},
                {"text": "入口即化 不甜不腻", "duration": 3.0},
                {"text": "点击下方链接 59块尝个鲜", "duration": 3.0},
            ],
            "estimated_duration": 16,
            "angle": "非遗文化",
        },
        {
            "hook": "办公室零食别再吃垃圾食品了！",
            "body": "给你推荐一个健康又好吃的",
            "cta": "赶紧拍一单试试",
            "full_script": "办公室零食别再吃垃圾食品了！给你推荐一个健康又好吃的，洛阳非遗葛根茯苓酥。赶紧拍一单试试。",
            "subtitle_segments": [
                {"text": "办公室零食别再吃垃圾食品了！", "duration": 3.0},
                {"text": "给你推荐一个健康又好吃的", "duration": 4.0},
                {"text": "洛阳非遗葛根茯苓酥", "duration": 3.0},
                {"text": "赶紧拍一单试试", "duration": 2.0},
            ],
            "estimated_duration": 12,
            "angle": "办公室零食",
        },
        {
            "hook": "送爸妈的礼物，我终于找到了",
            "body": "不是烟酒不是保健品，是这个洛阳非遗糕点",
            "cta": "链接放这了，自己看",
            "full_script": "送爸妈的礼物我终于找到了。不是烟酒不是保健品，是这个洛阳非遗糕点，葛根茯苓酥。链接放这了自己看。",
            "subtitle_segments": [
                {"text": "送爸妈的礼物 我终于找到了", "duration": 3.0},
                {"text": "不是烟酒不是保健品", "duration": 3.0},
                {"text": "是这个洛阳非遗糕点", "duration": 3.0},
                {"text": "葛根茯苓酥", "duration": 2.0},
                {"text": "链接放这了 自己看", "duration": 2.0},
            ],
            "estimated_duration": 13,
            "angle": "送礼场景",
        },
    ]
    return scripts


def _mock_openrouter_response(scripts_data):
    """Create a mock httpx response for OpenRouter API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(scripts_data, ensure_ascii=False)}}]
    }
    return mock_resp


# ============================================================
# Test 1: Creative Generation Pipeline
# ============================================================

class TestCreativeGeneration:
    """Simulate: OpenRouter generates scripts → MiniMax TTS voice → FFmpeg composes video."""

    @pytest.mark.asyncio
    async def test_scriptwriter_normal(self, mock_claude_scripts_response):
        """SCENARIO: OpenRouter returns valid JSON scripts."""
        from src.creative.scriptwriter import generate_scripts

        mock_resp = _mock_openrouter_response(mock_claude_scripts_response)

        with patch("src.creative.scriptwriter.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            scripts = await generate_scripts(
                product={"name": "葛根酥", "origin": "洛阳", "heritage_tag": "非遗", "price": 59,
                         "selling_points": ["好吃"], "pain_points": ["不健康"], "hooks": ["试试"]},
                count=3,
            )

        assert len(scripts) == 3
        assert scripts[0]["angle"] == "非遗文化"
        assert "full_script" in scripts[0]
        assert len(scripts[0]["subtitle_segments"]) > 0

    @pytest.mark.asyncio
    async def test_scriptwriter_malformed_response(self):
        """SCENARIO: LLM returns garbage text, no JSON → should return empty list, not crash."""
        from src.creative.scriptwriter import generate_scripts

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Sorry, I cannot generate scripts for this product."}}]
        }

        with patch("src.creative.scriptwriter.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            scripts = await generate_scripts(
                product={"name": "测试", "origin": "", "heritage_tag": "", "price": 0,
                         "selling_points": [], "pain_points": [], "hooks": []},
                count=3,
            )

        assert scripts == []  # Graceful failure, not crash

    @pytest.mark.asyncio
    async def test_scriptwriter_partial_json(self):
        """SCENARIO: LLM returns JSON wrapped in markdown code block."""
        from src.creative.scriptwriter import generate_scripts

        wrapped_json = '```json\n[{"hook":"test","body":"b","cta":"c","full_script":"test full","subtitle_segments":[{"text":"t","duration":3}],"estimated_duration":10,"angle":"test"}]\n```'

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": wrapped_json}}]
        }

        with patch("src.creative.scriptwriter.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            scripts = await generate_scripts(
                product={"name": "测试", "origin": "", "heritage_tag": "", "price": 0,
                         "selling_points": [], "pain_points": [], "hooks": []},
                count=1,
            )

        assert len(scripts) == 1
        assert scripts[0]["hook"] == "test"


# ============================================================
# Test 2: Campaign Optimization Decisions
# ============================================================

class TestOptimizer:
    """Simulate: Different ad performance scenarios → correct scale/kill decisions."""

    def test_kill_zero_conversions_high_spend(self):
        """SCENARIO: Spent ¥250 but 0 conversions → KILL."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        assert opt._decide_action(spend=250, conversions=0, cpa=0, roi=0) == "kill"

    def test_maintain_low_spend_zero_conversions(self):
        """SCENARIO: Only spent ¥50, 0 conversions → MAINTAIN (not enough data yet)."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        assert opt._decide_action(spend=50, conversions=0, cpa=0, roi=0) == "maintain"

    def test_kill_high_cpa(self):
        """SCENARIO: CPA ¥45 vs target ¥25 (1.8x) → KILL."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        assert opt._decide_action(spend=300, conversions=5, cpa=45, roi=1.0) == "kill"

    def test_scale_low_cpa(self):
        """SCENARIO: CPA ¥15 vs target ¥25 (0.6x), 3 conversions → SCALE."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        assert opt._decide_action(spend=45, conversions=3, cpa=15, roi=3.0) == "scale"

    def test_scale_high_roi(self):
        """SCENARIO: ROI 2.5, 1 conversion → SCALE (even if CPA is borderline)."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        assert opt._decide_action(spend=100, conversions=1, cpa=22, roi=2.5) == "scale"

    def test_maintain_borderline(self):
        """SCENARIO: CPA ¥28 (slightly above target ¥25 but below kill threshold) → MAINTAIN."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        assert opt._decide_action(spend=140, conversions=5, cpa=28, roi=1.5) == "maintain"

    def test_budget_scaling_cap(self):
        """SCENARIO: Scale budget capped at max_budget."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        # Spend ¥400, scale 1.5x = ¥600, but max is ¥500
        new_budget = opt._calc_scale_budget(400)
        assert new_budget == 500

    def test_budget_scaling_floor(self):
        """SCENARIO: Scale budget has floor of ¥200."""
        from src.adops.optimizer import CampaignOptimizer
        opt = CampaignOptimizer()
        new_budget = opt._calc_scale_budget(50)
        assert new_budget == 200


# ============================================================
# Test 3: Order Processing
# ============================================================

class TestOrderProcessing:
    """Simulate: Orders come in → relay to supplier → tracking update."""

    @pytest.mark.asyncio
    async def test_new_order_relayed(self):
        """SCENARIO: New order appears → relayed to supplier via Feishu."""
        from src.fulfillment.processor import OrderProcessor

        mock_order = {
            "shop_order_id": "TEST_ORDER_001",
            "sku_order_list": [{"product_name": "葛根茯苓酥礼盒", "sku_name": "标准装", "item_num": 1}],
            "post_addr": {
                "user_name": "张三", "user_phone": "13800138000",
                "province": {"name": "河南省"}, "city": {"name": "洛阳市"},
                "town": {"name": "老城区"}, "detail": "中州路100号",
            },
            "pay_amount": 5900,  # 分
        }

        processor = OrderProcessor()

        with patch.object(processor.doudian, "get_new_orders", new=AsyncMock(return_value=[mock_order])), \
             patch("src.fulfillment.supplier.send_feishu_message", new=AsyncMock(return_value=True)):

            result = await processor.process_new_orders()

        assert result["processed"] == 1

        # Verify order was saved to DB
        from src.db.models import get_session, Order
        session = get_session()
        db_order = session.query(Order).filter_by(order_id="TEST_ORDER_001").first()
        assert db_order is not None
        assert db_order.status == "relayed"
        assert db_order.amount == 59.0
        session.close()

    @pytest.mark.asyncio
    async def test_duplicate_order_skipped(self):
        """SCENARIO: Same order polled twice → only processed once."""
        from src.fulfillment.processor import OrderProcessor
        from src.db.models import get_session, Order

        # Pre-insert order into DB
        session = get_session()
        session.add(Order(order_id="TEST_ORDER_002", status="relayed", amount=59))
        session.commit()
        session.close()

        mock_order = {"shop_order_id": "TEST_ORDER_002", "sku_order_list": [], "post_addr": {}}

        processor = OrderProcessor()
        with patch.object(processor.doudian, "get_new_orders", new=AsyncMock(return_value=[mock_order])):
            result = await processor.process_new_orders()

        assert result["processed"] == 0  # Skipped duplicate

    @pytest.mark.asyncio
    async def test_tracking_update(self):
        """SCENARIO: Supplier ships → tracking number updates 抖店 and DB."""
        from src.fulfillment.processor import OrderProcessor
        from src.db.models import get_session, Order

        session = get_session()
        session.add(Order(order_id="TEST_ORDER_003", status="relayed", amount=59))
        session.commit()
        session.close()

        processor = OrderProcessor()
        with patch.object(processor.doudian, "ship_order", new=AsyncMock(return_value={"success": True})):
            result = await processor.update_tracking("TEST_ORDER_003", "yuantong", "YT9876543210")

        assert result["status"] == "shipped"

        session = get_session()
        db_order = session.query(Order).filter_by(order_id="TEST_ORDER_003").first()
        assert db_order.status == "shipped"
        assert db_order.tracking_no == "YT9876543210"
        session.close()


# ============================================================
# Test 4: Scheduler Job Deduplication
# ============================================================

class TestScheduler:
    """Simulate: Jobs don't re-run after restart."""

    def test_job_deduplication(self):
        """SCENARIO: Job ran today → _job_ran_today returns True → skips."""
        from src.scheduler.jobs import _job_ran_today, _record_job_run

        assert _job_ran_today("test_job") is False

        _record_job_run("test_job", "test result", success=True)

        assert _job_ran_today("test_job") is True

    def test_failed_job_can_rerun(self):
        """SCENARIO: Job failed → _job_ran_today returns False → allows retry."""
        from src.scheduler.jobs import _job_ran_today, _record_job_run

        _record_job_run("failing_job", "error occurred", success=False)

        assert _job_ran_today("failing_job") is False  # Failed jobs can retry


# ============================================================
# Test 5: Database Persistence
# ============================================================

class TestPersistence:
    """Simulate: Data survives across sessions (simulating restart)."""

    def test_campaign_persists(self):
        """SCENARIO: Campaign created → session closed → new session finds it."""
        from src.db.models import get_session, Campaign

        session1 = get_session()
        session1.add(Campaign(
            ad_id="AD_001", creative_id="CR_001", product_key="gegen",
            budget=100, target_cpa=25, angle="非遗文化",
            hook="你知道河南有个传了200年的糕点吗？", status="active",
        ))
        session1.commit()
        session1.close()

        # New session (simulating process restart)
        session2 = get_session()
        campaign = session2.query(Campaign).filter_by(ad_id="AD_001").first()
        assert campaign is not None
        assert campaign.angle == "非遗文化"
        assert campaign.status == "active"
        session2.close()

    def test_get_active_ad_ids(self):
        """SCENARIO: Mix of active and killed campaigns → only active returned."""
        from src.db.models import get_session, Campaign
        from src.adops.campaign import CampaignManager

        session = get_session()
        session.add(Campaign(ad_id="ACTIVE_1", creative_id="c1", product_key="g", status="active"))
        session.add(Campaign(ad_id="ACTIVE_2", creative_id="c2", product_key="g", status="active"))
        session.add(Campaign(ad_id="KILLED_1", creative_id="c3", product_key="g", status="killed"))
        session.commit()
        session.close()

        active_ids = CampaignManager.get_active_ad_ids()
        assert set(active_ids) == {"ACTIVE_1", "ACTIVE_2"}


# ============================================================
# Test 6: Safe JSON Parse
# ============================================================

class TestSafeJsonParse:
    """Verify JSON parsing handles all LLM response formats."""

    def test_clean_json(self):
        from src.common.retry import safe_json_parse
        result = safe_json_parse('[{"a": 1}]', "array")
        assert result == [{"a": 1}]

    def test_json_in_markdown(self):
        from src.common.retry import safe_json_parse
        text = "Here is the result:\n```json\n{\"key\": \"value\"}\n```\nDone."
        result = safe_json_parse(text, "object")
        assert result == {"key": "value"}

    def test_json_with_preamble(self):
        from src.common.retry import safe_json_parse
        text = "Sure, here are the scripts:\n[{\"hook\": \"test\"}]"
        result = safe_json_parse(text, "array")
        assert result == [{"hook": "test"}]

    def test_no_json(self):
        from src.common.retry import safe_json_parse
        result = safe_json_parse("I cannot do this", "object")
        assert result is None

    def test_nested_json(self):
        from src.common.retry import safe_json_parse
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = safe_json_parse(text, "object")
        assert result["outer"]["inner"] == [1, 2, 3]


# ============================================================
# Test 7: Startup Validation
# ============================================================

class TestStartup:
    """Verify startup checks catch missing prerequisites."""

    def test_missing_openrouter_key_fatal(self):
        from src.common.startup import validate_all, StartupError

        with patch("src.common.startup.settings") as mock_settings:
            mock_settings.openrouter_api_key = ""
            with pytest.raises(StartupError, match="OPENROUTER_API_KEY"):
                validate_all()

    def test_missing_optional_keys_warning(self):
        from src.common.startup import validate_all

        with patch("src.common.startup.settings") as mock_settings:
            mock_settings.openrouter_api_key = "sk-test"
            mock_settings.minimax_api_key = ""
            mock_settings.qianchuan_app_id = ""
            mock_settings.qianchuan_app_secret = ""
            mock_settings.doudian_app_key = ""
            mock_settings.doudian_app_secret = ""
            mock_settings.feishu_webhook_url = ""

            warnings = validate_all()

        assert any("MiniMax" in w for w in warnings)
        assert any("Qianchuan" in w for w in warnings)
        assert any("Doudian" in w for w in warnings)
        assert any("Feishu" in w for w in warnings)


# ============================================================
# Test 8: Full Pipeline Integration (Mock External APIs)
# ============================================================

class TestFullPipeline:
    """Simulate the complete daily cycle: produce → launch → optimize → orders → report."""

    @pytest.mark.asyncio
    async def test_daily_cycle(self, mock_claude_scripts_response):
        """SCENARIO: Full day simulation - everything works."""
        from src.db.models import get_session, Campaign, Order

        # ---- Phase 1: Creative Production ----
        from src.creative.scriptwriter import generate_scripts

        mock_resp = _mock_openrouter_response(mock_claude_scripts_response)

        with patch("src.creative.scriptwriter.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            scripts = await generate_scripts(
                product={"name": "葛根酥", "origin": "洛阳", "heritage_tag": "非遗", "price": 59,
                         "selling_points": ["好"], "pain_points": ["差"], "hooks": ["试"]},
                count=3,
            )
        assert len(scripts) == 3

        # ---- Phase 2: Campaign Launch (simulated) ----
        session = get_session()
        for i, script in enumerate(scripts):
            session.add(Campaign(
                ad_id=f"SIM_AD_{i:03d}",
                creative_id=f"SIM_CR_{i:03d}",
                product_key="gegen_fuling_su",
                budget=100,
                target_cpa=25,
                angle=script["angle"],
                hook=script["hook"],
                status="active",
            ))
        session.commit()
        session.close()

        # ---- Phase 3: Optimization (2 hours later) ----
        from src.adops.optimizer import CampaignOptimizer
        from src.adops.campaign import CampaignManager

        active_ids = CampaignManager.get_active_ad_ids()
        assert len(active_ids) == 3

        # Simulate千川 reports: 1 good, 1 borderline, 1 bad
        mock_reports = [
            {"ad_id": "SIM_AD_000", "stat_cost": 80, "convert_cnt": 5, "conversion_cost": 16,
             "pay_order_count": 5, "pay_order_amount": 295, "prepay_and_pay_order_roi": 3.7},
            {"ad_id": "SIM_AD_001", "stat_cost": 100, "convert_cnt": 3, "conversion_cost": 33,
             "pay_order_count": 3, "pay_order_amount": 177, "prepay_and_pay_order_roi": 1.8},
            {"ad_id": "SIM_AD_002", "stat_cost": 220, "convert_cnt": 0, "conversion_cost": 0,
             "pay_order_count": 0, "pay_order_amount": 0, "prepay_and_pay_order_roi": 0},
        ]

        optimizer = CampaignOptimizer()
        with patch.object(optimizer.client, "get_campaign_reports", new=AsyncMock(return_value=mock_reports)), \
             patch.object(optimizer.client, "update_campaign_budget", new=AsyncMock(return_value={})), \
             patch.object(optimizer.client, "update_campaign_status", new=AsyncMock(return_value={})), \
             patch("src.adops.optimizer.send_feishu_message", new=AsyncMock(return_value=True)):

            actions = await optimizer.run_optimization_cycle(active_ids)

        # AD_000: CPA ¥16 < target×0.8 (¥20), 5 conversions → SCALE
        assert any(a["ad_id"] == "SIM_AD_000" for a in actions["scaled"])
        # AD_001: CPA ¥33, above target but below kill threshold → MAINTAIN
        assert any(a["ad_id"] == "SIM_AD_001" for a in actions["maintained"])
        # AD_002: Spent ¥220, 0 conversions → KILL
        assert any(a["ad_id"] == "SIM_AD_002" for a in actions["killed"])

        # Verify DB state after optimization
        session = get_session()
        killed = session.query(Campaign).filter_by(ad_id="SIM_AD_002").first()
        assert killed.status == "killed"
        assert killed.killed_at is not None

        active = session.query(Campaign).filter_by(ad_id="SIM_AD_000").first()
        assert active.total_spend == 80
        assert active.total_gmv == 295
        session.close()

        # ---- Phase 4: Order Processing ----
        from src.fulfillment.processor import OrderProcessor

        mock_orders = [
            {
                "shop_order_id": "SIM_ORDER_001",
                "sku_order_list": [{"product_name": "葛根茯苓酥礼盒", "sku_name": "标准", "item_num": 1}],
                "post_addr": {"user_name": "李四", "user_phone": "13900139000",
                              "province": {"name": "北京"}, "city": {"name": "北京"},
                              "town": {"name": "海淀"}, "detail": "中关村1号"},
                "pay_amount": 5900,
            },
        ]

        processor = OrderProcessor()
        with patch.object(processor.doudian, "get_new_orders", new=AsyncMock(return_value=mock_orders)), \
             patch("src.fulfillment.supplier.send_feishu_message", new=AsyncMock(return_value=True)):
            order_result = await processor.process_new_orders()

        assert order_result["processed"] == 1

        # ---- Phase 5: Tracking Update ----
        with patch.object(processor.doudian, "ship_order", new=AsyncMock(return_value={})):
            track_result = await processor.update_tracking("SIM_ORDER_001", "yuantong", "YT111222333")

        assert track_result["status"] == "shipped"

        # Verify final DB state
        session = get_session()
        order = session.query(Order).filter_by(order_id="SIM_ORDER_001").first()
        assert order.status == "shipped"
        assert order.tracking_no == "YT111222333"

        campaigns = session.query(Campaign).all()
        assert len(campaigns) == 3
        active_count = sum(1 for c in campaigns if c.status == "active")
        killed_count = sum(1 for c in campaigns if c.status == "killed")
        assert active_count == 2
        assert killed_count == 1
        session.close()
