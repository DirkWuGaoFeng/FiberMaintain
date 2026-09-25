"""
结果聚合节点集成测试 [v7.4]。

覆盖两个新接线点：
1. 用户记忆偏好注入（有 user_id 时注入，无时静默跳过）
2. 输出脱敏（output_filter 对 final_output 统一过滤）
"""

import pytest

from src.graph.state import create_initial_state
from src.nodes.result_aggregator import result_aggregator_node


class TestOutputSanitization:
    """输出脱敏：IP 掩码 + 内部错误详情隐藏."""

    @pytest.mark.asyncio
    async def test_ip_masked_in_final_output(self):
        """final_output 中的 IP 应被掩码为 x.x.*.*."""
        state = create_initial_state("查询光纤1的衰耗")
        state["final_output"] = "后端地址为 192.168.1.1:8080，请访问"
        updates = await result_aggregator_node(state)
        assert "192.168.*.*" in updates["final_output"]
        assert "192.168.1.1" not in updates["final_output"]

    @pytest.mark.asyncio
    async def test_internal_error_hidden(self):
        """内部 traceback 应被脱敏为提示信息."""
        state = create_initial_state("查询光纤1的衰耗")
        state["final_output"] = (
            "查询失败\nTraceback (most recent call last):\n"
            '  File "/app/src/x.py", line 12, in f\n    raise ValueError'
        )
        updates = await result_aggregator_node(state)
        assert "内部错误详情已隐藏" in updates["final_output"]
        assert "Traceback" not in updates["final_output"]

    @pytest.mark.asyncio
    async def test_no_user_id_no_preferences(self):
        """无 user_id → 不注入偏好，user_preferences 不存在."""
        state = create_initial_state("查询光纤1的衰耗")
        state["user_id"] = None
        state["final_output"] = "正常输出"
        updates = await result_aggregator_node(state)
        assert "user_preferences" not in updates


class TestUserMemoryInjection:
    """用户记忆偏好注入."""

    @pytest.mark.asyncio
    async def test_user_preferences_injected(self, monkeypatch):
        """有 user_id → 注入偏好到 user_preferences."""

        class FakeManager:
            def inject_preferences(self, user_id, context):
                return {"output_format": "table", "language": "zh"}

        monkeypatch.setattr(
            "src.nodes.result_aggregator.get_user_memory_manager",
            lambda: FakeManager(),
        )

        state = create_initial_state("查询光纤1的衰耗")
        state["user_id"] = "u-001"
        state["final_output"] = "正常输出"
        updates = await result_aggregator_node(state)
        assert updates["user_preferences"]["output_format"] == "table"
        assert updates["user_preferences"]["language"] == "zh"

    @pytest.mark.asyncio
    async def test_inject_exception_silently_skipped(self, monkeypatch):
        """注入抛异常 → 静默跳过，不报错、不注入."""

        def _boom(user_id, context):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.nodes.result_aggregator.get_user_memory_manager",
            lambda: type("M", (), {"inject_preferences": _boom})(),
        )

        state = create_initial_state("查询光纤1的衰耗")
        state["user_id"] = "u-001"
        state["final_output"] = "正常输出"
        updates = await result_aggregator_node(state)
        assert "user_preferences" not in updates
        assert updates["final_output"] == "正常输出"
