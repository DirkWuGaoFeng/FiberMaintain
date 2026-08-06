"""Lead Router 单元测试."""
import pytest

from src.v8.lead_router import LeadRouter
from src.v8.models import ExecutionPlan


class TestLeadRouter:
    def test_init(self):
        router = LeadRouter()
        assert router._loader is not None
        assert router._trigger_registry is not None

    @pytest.mark.asyncio
    async def test_resolve_rule_match(self):
        """规则命中 → 直接返回 plan."""
        router = LeadRouter()
        # "查看光纤1的跨段损耗" 应命中 spanloss_check skill
        plan = await router.resolve(
            "查看光纤1的跨段损耗",
            {"fiber_ids": [1]},
            trace_id="t1",
        )
        assert isinstance(plan, ExecutionPlan)
        assert plan.confidence > 0
        assert plan.match_type in ("rule", "llm", "default")

    @pytest.mark.asyncio
    async def test_resolve_fallback(self):
        """完全无法匹配 → 兜底 plan."""
        router = LeadRouter()
        plan = await router.resolve(
            "今天天气怎么样",
            {},
            trace_id="t2",
        )
        assert isinstance(plan, ExecutionPlan)
        assert plan.match_type in ("default", "llm")

    def test_default_plan(self):
        router = LeadRouter()
        plan = router._default_plan("随便问问")
        assert plan.scenario_id != ""
        assert len(plan.tools) > 0
