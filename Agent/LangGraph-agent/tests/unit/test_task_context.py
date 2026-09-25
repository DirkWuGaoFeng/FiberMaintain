"""TaskContext 单测（书籍 Ch2：任务上下文显式化）。"""

from src.context.task_context import (
    _derive_next_step,
    _derive_task_plan,
    build_task_context,
)


class TestTaskPlan:
    def test_spanloss_plan(self):
        plan = _derive_task_plan({"intent": "spanloss_analysis", "normalized_params": {"fiber_ids": [5]}})
        assert "光纤[5]" in plan
        assert "参数归一化与验证" in plan

    def test_unknown_intent_fallback(self):
        plan = _derive_task_plan({"intent": "", "user_input": "查一下光纤"})
        assert "任务：查一下光纤" in plan


class TestNextStep:
    def _plan(self):
        return _derive_task_plan({"intent": "spanloss_analysis", "normalized_params": {"fiber_ids": [5]}})

    def test_empty_progress(self):
        assert _derive_next_step(self._plan(), []) == "参数归一化与验证"

    def test_partial_progress(self):
        assert _derive_next_step(self._plan(), ["意图分类", "参数归一化与验证", "数据采集"]) == "程序化判断"

    def test_all_done(self):
        assert (
            _derive_next_step(
                self._plan(),
                ["参数归一化与验证", "数据采集", "程序化判断", "LLM 分析评估", "叙述生成"],
            )
            == "全部完成，等待结果聚合"
        )


class TestBuildTaskContext:
    def test_derives_from_state(self):
        ctx = build_task_context(
            {
                "intent": "spanloss_analysis",
                "normalized_params": {"fiber_ids": [5]},
                "collected_data_summary": "数据已收集",
            }
        )
        assert "任务计划" in ctx
        assert "数据采集" in ctx  # 已完成步骤
        assert "下一步" in ctx

    def test_empty_state_safe(self):
        ctx = build_task_context({})
        assert "任务计划" in ctx
        assert "已完成步骤" in ctx
