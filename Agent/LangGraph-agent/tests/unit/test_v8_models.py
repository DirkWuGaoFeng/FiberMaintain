"""v8 数据模型单元测试."""
import pytest

from src.v8.models import (
    AgentLayer,
    AgentResult,
    ExecutionPlan,
    LoopContext,
    V8State,
)


class TestExecutionPlan:
    def test_default_values(self):
        plan = ExecutionPlan()
        assert plan.max_loop_rounds == 3
        assert plan.analysis_mode == "rule_first"
        assert plan.tools == []

    def test_from_skill_yaml_fields(self):
        plan = ExecutionPlan(
            scenario_id="spanloss_check",
            intent="spanloss_check",
            confidence=0.95,
            match_type="rule",
            tools=["fiber_spanloss_query", "fiber_connection_query"],
            judgment_rules=["spanloss_threshold"],
            threshold_refs=["default_spanloss"],
            output_format="narrative",
        )
        assert len(plan.tools) == 2
        assert plan.threshold_refs == ["default_spanloss"]

    def test_serialization_roundtrip(self):
        plan = ExecutionPlan(scenario_id="test", tools=["a", "b"])
        data = plan.model_dump()
        restored = ExecutionPlan.model_validate(data)
        assert restored == plan


class TestAgentResult:
    def test_success_result(self):
        r = AgentResult(layer=AgentLayer.COLLECTION, data={"fibers": [1, 2]})
        assert r.success
        assert not r.needs_more_data

    def test_needs_more_data_signal(self):
        r = AgentResult(
            layer=AgentLayer.ANALYSIS,
            needs_more_data=True,
            additional_query={"tool": "alarm_query", "params": {"fiber_id": 1}},
        )
        assert r.needs_more_data
        assert r.additional_query["tool"] == "alarm_query"


class TestLoopContext:
    def test_initial_state(self):
        ctx = LoopContext(max_rounds=3)
        assert ctx.round == 0
        assert ctx.terminated_reason == ""

    def test_termination(self):
        ctx = LoopContext(round=3, max_rounds=3, terminated_reason="max_rounds")
        assert ctx.round >= ctx.max_rounds


class TestV8State:
    def test_full_lifecycle(self):
        state = V8State(user_input="查看光纤1", trace_id="t-001")
        state.execution_plan = ExecutionPlan(scenario_id="spanloss_check")
        state.collection_result = AgentResult(
            layer=AgentLayer.COLLECTION, data={"spanloss": 3.2}
        )
        assert state.execution_plan.scenario_id == "spanloss_check"
        assert state.collection_result.data["spanloss"] == 3.2
