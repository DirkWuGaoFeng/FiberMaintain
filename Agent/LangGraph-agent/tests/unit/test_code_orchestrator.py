"""CodeOrchestrator 单测：保留集校验与失败恢复（书籍 Ch5）。"""

import pytest

from src.tools.code_orchestrator import (
    CodeOrchestrator,
    CodePlan,
    CodeStep,
)


def _plan(goal: str) -> CodePlan:
    return CodeOrchestrator().plan_from_goal(goal)


class TestRetentionSet:
    def test_statistics_plan_has_retention(self):
        plan = _plan("统计衰耗平均值")
        assert set(plan.retention_set) == {"count", "mean", "min", "max"}

    def test_statistics_success_retains_keys(self):
        data = [d["value"] if isinstance(d, dict) else d for d in [{"value": 3}, {"value": 5}, {"value": 7}]]
        result = CodeOrchestrator().execute_plan(_plan("统计衰耗平均值"), context={"data": data})
        assert result.success and not result.recovered

    def test_retention_violation_fails(self):
        # 步骤把 result 改成缺失保留键的形态 → 必须判失败
        plan = CodePlan(
            goal="g",
            steps=[CodeStep(description="破坏保留集", code="result = {'x': 1}")],
            safety_checks=[],
            retention_set=["count", "mean"],
        )
        result = CodeOrchestrator().execute_plan(plan)
        assert not result.success
        assert "保留集缺失" in result.error


class TestRecovery:
    def test_recovery_marks_degraded_success(self):
        # 步骤必然抛异常 → 正常执行失败，恢复后为兜底成功
        plan = CodePlan(
            goal="g",
            steps=[CodeStep(description="step", code="raise RuntimeError('boom')")],
            safety_checks=[],
            retention_set=["count"],
        )
        base = CodeOrchestrator().execute_plan(plan)
        assert not base.success

        recovered = CodeOrchestrator().execute_plan_with_recovery(plan)
        assert recovered.success
        assert recovered.recovered

    def test_recovery_disabled_returns_base_failure(self):
        plan = CodePlan(
            goal="g",
            steps=[CodeStep(description="step", code="raise RuntimeError('boom')")],
            safety_checks=[],
            retention_set=["count"],
        )
        result = CodeOrchestrator().execute_plan_with_recovery(plan, max_recovery_attempts=0)
        assert not result.success
        assert not result.recovered

    def test_recovery_passthrough_on_success(self):
        data = [3, 5, 7]
        plan = _plan("统计衰耗平均值")
        result = CodeOrchestrator().execute_plan_with_recovery(plan, context={"data": data})
        assert result.success
        assert not result.recovered


class TestToolRegistration:
    """code_orchestrator 注册为 LangChain Tool [P2]."""

    def test_execute_code_plan_registered_in_init(self):
        """tools/__init__ 导出 execute_code_plan."""
        from src.tools import CODING_TOOLS, execute_code_plan

        assert execute_code_plan in CODING_TOOLS
        assert execute_code_plan.name == "execute_code_plan"

    @pytest.mark.asyncio
    async def test_execute_code_plan_statistics_success(self):
        """工具调用统计目标 → 返回成功 JSON."""
        import json

        from src.tools.code_orchestrator import execute_code_plan

        result = await execute_code_plan.ainvoke(
            {
                "goal": "统计衰耗平均值",
                "data_json": json.dumps([{"value": 3}, {"value": 5}, {"value": 7}]),
            }
        )
        data = json.loads(result)
        assert data["status"] == "success"
        assert "count': 3" in data["output"]

    @pytest.mark.asyncio
    async def test_execute_code_plan_invalid_json(self):
        """data_json 非法 JSON → 抛出 ValueError."""
        from src.tools.code_orchestrator import execute_code_plan

        with pytest.raises(ValueError):
            await execute_code_plan.ainvoke(
                {
                    "goal": "统计",
                    "data_json": "not-json",
                }
            )
