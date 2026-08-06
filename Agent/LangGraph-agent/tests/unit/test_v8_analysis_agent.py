"""Analysis Agent 单元测试."""
import pytest

from src.v8.agents.analysis_agent import AnalysisAgent
from src.v8.contracts import CollectionPayload, FiberMetrics
from src.v8.models import AgentLayer, ExecutionPlan


class TestAnalysisAgent:
    def test_layer(self):
        agent = AnalysisAgent()
        assert agent.layer == AgentLayer.ANALYSIS

    def test_rule_judgment_typed_normal(self):
        """结构化数据 → 规则判断 NORMAL."""
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        payload = CollectionPayload(
            metrics=[FiberMetrics(fiber_id=1, spanloss_db=2.5)],
        )
        verdict = agent._rule_judgment_typed(payload, plan)
        assert verdict.status == "NORMAL"
        assert len(verdict.findings) == 1
        assert verdict.findings[0].level == "NORMAL"

    def test_rule_judgment_typed_warning(self):
        """结构化数据 → 规则判断 WARNING."""
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        payload = CollectionPayload(
            metrics=[FiberMetrics(fiber_id=1, spanloss_db=5.5)],
        )
        verdict = agent._rule_judgment_typed(payload, plan)
        assert verdict.status in ("WARNING", "CRITICAL")

    def test_rule_judgment_typed_critical(self):
        """结构化数据 → 规则判断 CRITICAL."""
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        payload = CollectionPayload(
            metrics=[FiberMetrics(fiber_id=1, spanloss_db=9.0)],
        )
        verdict = agent._rule_judgment_typed(payload, plan)
        assert verdict.status == "CRITICAL"

    def test_rule_judgment_typed_oop_abnormal(self):
        """结构化 OOP 异常."""
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        payload = CollectionPayload(
            metrics=[FiberMetrics(fiber_id=1, oop_dbm=-12.5)],
        )
        verdict = agent._rule_judgment_typed(payload, plan)
        assert verdict.status != "NORMAL"

    def test_rule_judgment_no_data(self):
        """无数据 → UNKNOWN."""
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        payload = CollectionPayload()
        verdict = agent._rule_judgment_typed(payload, plan)
        assert verdict.status == "UNKNOWN"

    def test_regex_fallback(self):
        """ReAct 路径的 regex fallback 仍然工作."""
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        payload = CollectionPayload(
            raw_summary="跨段损耗 3.0 dB",
            collection_mode="react",
        )
        verdict = agent._rule_judgment_typed(payload, plan)
        assert verdict.status == "NORMAL"
        assert len(verdict.findings) == 1

    @pytest.mark.asyncio
    async def test_execute_structured_path(self):
        """结构化数据走规则路径."""
        agent = AnalysisAgent()
        plan = ExecutionPlan(analysis_mode="rule_first")
        ctx = {
            "trace_id": "t1",
            "collection_data": {
                "metrics": [{"fiber_id": 1, "spanloss_db": 3.0}],
                "collection_mode": "deterministic",
            },
            "user_input": "查看光纤1",
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data["analysis_mode"] == "rule"
        assert result.data["verdict"]["status"] == "NORMAL"

    @pytest.mark.asyncio
    async def test_execute_legacy_raw_summary(self):
        """兼容旧格式 raw_summary."""
        agent = AnalysisAgent()
        plan = ExecutionPlan(analysis_mode="rule_first")
        ctx = {
            "trace_id": "t1",
            "collection_data": {"raw_summary": "跨段损耗 9.0 dB"},
            "user_input": "查看光纤1",
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data["verdict"]["status"] == "CRITICAL"
