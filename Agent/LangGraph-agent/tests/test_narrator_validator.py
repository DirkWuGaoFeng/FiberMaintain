"""
叙述校验器单元测试 [v7.1]。

测试 4 条程序化校验规则：
1. 数值逐字出现
2. 颜色词匹配
3. 无幻觉告警类型
4. 严重级别一致性
"""

import pytest

from src.nodes.narrator_validator import narrator_validator_node


class TestNarratorValidator:
    """测试 NarratorValidator 程序化校验。"""

    @pytest.mark.asyncio
    async def test_valid_narration_passes(self):
        """正确的叙述应通过校验。"""
        state = {
            "narration": "光纤1的衰耗为6.5dB，超过阈值5.0dB，状态为WARNING。",
            "rule_judgment": {
                "status": "WARNING",
                "findings": ["衰耗6.5dB超过阈值5.0dB"],
                "metrics": {"spanloss": 6.5},
                "suggested_actions": ["检查光纤连接头"],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is True

    @pytest.mark.asyncio
    async def test_numeric_tampering_fails(self):
        """篡改后的数值应无法通过校验。"""
        state = {
            "narration": "光纤1的衰耗为3.2dB，状态正常。",  # 3.2 不在 judgment 中
            "rule_judgment": {
                "status": "WARNING",
                "findings": ["衰耗6.5dB超过阈值5.0dB"],
                "metrics": {"spanloss": 6.5},
                "suggested_actions": [],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is False

    @pytest.mark.asyncio
    async def test_color_mismatch_fails(self):
        """提及错误的颜色应失败。"""
        state = {
            "narration": "光纤颜色为绿色，状态正常。",
            "rule_judgment": {
                "status": "CRITICAL",
                "findings": ["光纤颜色变为红色"],
                "metrics": {"color": "RED"},
                "suggested_actions": [],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is False

    @pytest.mark.asyncio
    async def test_severity_mismatch_fails(self):
        """严重级别不一致应失败。"""
        state = {
            "narration": "光纤状态正常，无需处理。",
            "rule_judgment": {
                "status": "CRITICAL",
                "findings": ["严重告警"],
                "metrics": {},
                "suggested_actions": ["立即处理"],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is False

    @pytest.mark.asyncio
    async def test_empty_narration_passes(self):
        """空叙述跳过校验（没有可校验的判断依据）。"""
        state = {
            "narration": "",
            "rule_judgment": {"status": "NORMAL", "findings": [], "metrics": {}},
        }
        result = await narrator_validator_node(state)
        # 空叙述表示跳过校验 -> 通过
        assert result["narrator_validation_passed"] is True

    @pytest.mark.asyncio
    async def test_no_judgment_passes(self):
        """无判断数据意味着没有可校验的内容。"""
        state = {
            "narration": "这是一般性回复。",
            "rule_judgment": None,
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is True
