"""
多轮追问上下文恢复测试。

【测试场景】
验证当用户在追问后回复补充信息时，系统能正确恢复上一轮的意图上下文。

例如：
  轮次1: "查询光纤衰耗" → 追问 "请告诉我您要查询哪根光纤的衰耗"
  轮次2: "光纤3" → 应识别为 spanloss_query + fiber_id=3
"""

from __future__ import annotations

import pytest


class TestClarificationContextRestoration:
    """测试 _restore_clarification_context 函数。"""

    @pytest.mark.asyncio
    async def test_restore_spanloss_context(self):
        """测试：追问后回复 '光纤3' 应恢复 spanloss_query 意图。"""
        from unittest.mock import AsyncMock, MagicMock

        from src.server import _restore_clarification_context

        # 模拟上一轮状态（clarification）
        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {
            "processing_path": "clarification",
            "intent": "spanloss_query",
        }
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        # 当前轮次状态
        state = {"user_input": "光纤3"}

        # 执行恢复
        await _restore_clarification_context(mock_graph, state, "thread-1", "光纤3")

        # 验证：意图应被恢复
        assert state["intent"] == "spanloss_query"
        assert state["rule_match"]["intent"] == "spanloss_query"
        assert state["rule_match"]["params"]["fiber_id"] == 3
        assert state["processing_path"] == "fast"

    @pytest.mark.asyncio
    async def test_restore_with_bare_number(self):
        """测试：追问后回复纯数字 '3' 也应恢复上下文。"""
        from unittest.mock import AsyncMock, MagicMock

        from src.server import _restore_clarification_context

        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {
            "processing_path": "clarification",
            "intent": "spanloss_query",
        }
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        state = {"user_input": "3"}
        await _restore_clarification_context(mock_graph, state, "thread-1", "3")

        assert state["intent"] == "spanloss_query"
        assert state["rule_match"]["params"]["fiber_id"] == 3

    @pytest.mark.asyncio
    async def test_restore_with_number_suffix(self):
        """测试：追问后回复 '3号' 也应恢复上下文。"""
        from unittest.mock import AsyncMock, MagicMock

        from src.server import _restore_clarification_context

        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {
            "processing_path": "clarification",
            "intent": "spanloss_analysis",
        }
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        state = {"user_input": "3号"}
        await _restore_clarification_context(mock_graph, state, "thread-1", "3号")

        assert state["intent"] == "spanloss_analysis"
        assert state["rule_match"]["params"]["fiber_id"] == 3

    @pytest.mark.asyncio
    async def test_no_restore_when_no_previous_clarification(self):
        """测试：上一轮不是 clarification 时不应恢复。"""
        from unittest.mock import AsyncMock, MagicMock

        from src.server import _restore_clarification_context

        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {
            "processing_path": "normal",  # 不是 clarification
            "intent": "spanloss_query",
        }
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        state = {"user_input": "光纤3"}
        await _restore_clarification_context(mock_graph, state, "thread-1", "光纤3")

        # 不应修改 state
        assert "intent" not in state or state.get("intent") is None

    @pytest.mark.asyncio
    async def test_no_restore_when_no_previous_state(self):
        """测试：没有上一轮状态时不应恢复。"""
        from unittest.mock import AsyncMock, MagicMock

        from src.server import _restore_clarification_context

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=None)

        state = {"user_input": "光纤3"}
        await _restore_clarification_context(mock_graph, state, "thread-1", "光纤3")

        # 不应修改 state
        assert "intent" not in state or state.get("intent") is None

    @pytest.mark.asyncio
    async def test_no_restore_when_input_not_parameter(self):
        """测试：当前输入不是参数值时不应恢复。"""
        from unittest.mock import AsyncMock, MagicMock

        from src.server import _restore_clarification_context

        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {
            "processing_path": "clarification",
            "intent": "spanloss_query",
        }
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        state = {"user_input": "你好"}  # 不是参数值
        await _restore_clarification_context(mock_graph, state, "thread-1", "你好")

        # 不应修改 state
        assert "intent" not in state or state.get("intent") is None


class TestBuildContextFromMessages:
    """测试 _build_context_from_messages 函数。"""

    def test_empty_messages(self):
        """测试：空消息列表返回空字符串。"""
        from src.nodes.intent_classifier import _build_context_from_messages

        result = _build_context_from_messages([])
        assert result == ""

    def test_single_message(self):
        """测试：只有当前输入时返回空字符串。"""
        from langchain_core.messages import HumanMessage

        from src.nodes.intent_classifier import _build_context_from_messages

        messages = [HumanMessage(content="光纤3")]
        result = _build_context_from_messages(messages)
        assert result == ""

    def test_with_history(self):
        """测试：有对话历史时返回格式化的上下文。"""
        from langchain_core.messages import AIMessage, HumanMessage

        from src.nodes.intent_classifier import _build_context_from_messages

        messages = [
            HumanMessage(content="查询光纤衰耗"),
            AIMessage(content="请告诉我您要查询哪根光纤的衰耗"),
            HumanMessage(content="光纤3"),
        ]
        result = _build_context_from_messages(messages)

        assert "对话历史" in result
        assert "查询光纤衰耗" in result
        assert "请告诉我您要查询哪根光纤的衰耗" in result
        # 当前输入不应包含
        assert "光纤3" not in result

    def test_truncation(self):
        """测试：长内容应被截断。"""
        from langchain_core.messages import HumanMessage

        from src.nodes.intent_classifier import _build_context_from_messages

        long_content = "x" * 200
        messages = [
            HumanMessage(content=long_content),
            HumanMessage(content="当前输入"),
        ]
        result = _build_context_from_messages(messages)

        # 应被截断到 100 字符
        assert len(result) < 200
