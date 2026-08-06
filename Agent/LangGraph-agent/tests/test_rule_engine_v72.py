"""
Unit tests for Rule Engine v7.2 new rules (R101-R105).

Tests colloquial query patterns added in v7.2:
- R101: 连纤查询 ("分析连纤1中断的原因", "连纤3")
- R102: 连纤颜色/状态 ("连纤3颜色", "连纤5的状态")
- R103: 断纤查询 ("目前断纤有哪些", "当前中断光纤列表")
- R104: 光纤中断分析 ("光纤3中断的原因")
- R105: 口语化衰耗 ("光纤5衰耗", "连纤2的损耗")
- Rule priority: existing rules not shadowed
"""

import pytest

from src.nodes.rule_engine import RuleEngine


class TestR101ConnectionQuery:
    """R101: 连纤查询（口语化连接查询）"""

    def test_r101_connection_interrupt(self):
        """'分析连纤1中断的原因' → connection_query, fast_path"""
        result = RuleEngine.match("分析连纤1中断的原因")
        assert result is not None
        assert result.intent == "connection_query"
        assert result.params.get("fiber_id") == 1
        assert result.fast_path_eligible is True
        assert result.confidence == 1.0

    def test_r101_simple_connection(self):
        """'连纤3' → connection_query"""
        result = RuleEngine.match("连纤3")
        assert result is not None
        assert result.intent == "connection_query"
        assert result.params.get("fiber_id") == 3
        assert result.fast_path_eligible is True

    def test_r101_diagnose_connection(self):
        """'诊断连纤5故障' → connection_query"""
        result = RuleEngine.match("诊断连纤5故障")
        assert result is not None
        assert result.intent == "connection_query"
        assert result.params.get("fiber_id") == 5

    def test_r101_with_space(self):
        """'连纤 12 中断' → connection_query, fiber_id=12"""
        result = RuleEngine.match("连纤 12 中断")
        assert result is not None
        assert result.intent == "connection_query"
        assert result.params.get("fiber_id") == 12


class TestR102ConnectionColor:
    """R102: 连纤颜色/状态查询"""

    def test_r102_connection_color(self):
        """'连纤3颜色' → single_query, fast_path"""
        result = RuleEngine.match("连纤3颜色")
        assert result is not None
        assert result.intent == "single_query"
        assert result.params.get("fiber_id") == 3
        assert result.fast_path_eligible is True

    def test_r102_connection_status(self):
        """'连纤5的状态' → single_query"""
        result = RuleEngine.match("连纤5的状态")
        assert result is not None
        assert result.intent == "single_query"
        assert result.params.get("fiber_id") == 5

    def test_r102_connection_color_label(self):
        """'连纤2色标' → single_query"""
        result = RuleEngine.match("连纤2色标")
        assert result is not None
        assert result.intent == "single_query"
        assert result.params.get("fiber_id") == 2

    def test_r102_with_de_particle(self):
        """'连纤7的颜色' → single_query"""
        result = RuleEngine.match("连纤7的颜色")
        assert result is not None
        assert result.intent == "single_query"
        assert result.params.get("fiber_id") == 7


class TestR103BrokenFibers:
    """R103: 断纤查询"""

    def test_r103_broken_fibers(self):
        """'目前断纤有哪些' → colored_query, color=RED"""
        result = RuleEngine.match("目前断纤有哪些")
        assert result is not None
        assert result.intent == "colored_query"
        assert result.params.get("color") == "RED"
        assert result.fast_path_eligible is True

    def test_r103_broken_fibers_alt(self):
        """'当前中断光纤列表' → colored_query"""
        result = RuleEngine.match("当前中断光纤列表")
        assert result is not None
        assert result.intent == "colored_query"
        assert result.params.get("color") == "RED"

    def test_r103_broken_fibers_count(self):
        """'断纤多少' → colored_query"""
        result = RuleEngine.match("断纤多少")
        assert result is not None
        assert result.intent == "colored_query"

    def test_r103_now_broken(self):
        """'现在断开的光纤' → colored_query"""
        result = RuleEngine.match("现在断开的光纤")
        assert result is not None
        assert result.intent == "colored_query"


class TestR104FiberInterruptAnalysis:
    """R104: 光纤中断分析（非快速路径）"""

    def test_r104_fiber_interrupt_analysis(self):
        """'光纤3中断的原因' → spanloss_analysis, NOT fast_path"""
        result = RuleEngine.match("光纤3中断的原因")
        assert result is not None
        assert result.intent == "spanloss_analysis"
        assert result.params.get("fiber_id") == 3
        assert result.fast_path_eligible is False

    def test_r104_fib_format(self):
        """'FIB-0005断开分析' → spanloss_analysis"""
        result = RuleEngine.match("FIB-0005断开分析")
        assert result is not None
        assert result.intent == "spanloss_analysis"
        assert result.params.get("fiber_id") == 5
        assert result.fast_path_eligible is False

    def test_r104_fiber_fault(self):
        """'光纤12故障' → spanloss_analysis"""
        result = RuleEngine.match("光纤12故障")
        assert result is not None
        assert result.intent == "spanloss_analysis"
        assert result.params.get("fiber_id") == 12


class TestR105ColloquialSpanloss:
    """R105: 口语化衰耗查询"""

    def test_r105_colloquial_spanloss(self):
        """'光纤5衰耗' → spanloss_query, fast_path"""
        result = RuleEngine.match("光纤5衰耗")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.params.get("fiber_id") == 5
        assert result.fast_path_eligible is True

    def test_r105_connection_spanloss(self):
        """'连纤2的损耗' → spanloss_query"""
        result = RuleEngine.match("连纤2的损耗")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.params.get("fiber_id") == 2

    def test_r105_fib_spanloss(self):
        """'FIB-0008 spanloss' → spanloss_query"""
        result = RuleEngine.match("FIB-0008 spanloss")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.params.get("fiber_id") == 8


class TestRulePriority:
    """Ensure new rules don't shadow existing rules."""

    def test_existing_spanloss_rule_priority(self):
        """'查询光纤1的衰耗' still matches R001 (spanloss_query)."""
        result = RuleEngine.match("查询光纤1的衰耗")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.params.get("fiber_id") == 1
        assert result.fast_path_eligible is True

    def test_existing_connection_rule_priority(self):
        """'查询光纤3的连纤' still matches R002 (connection_query)."""
        result = RuleEngine.match("查询光纤3的连纤")
        assert result is not None
        assert result.intent == "connection_query"
        assert result.params.get("fiber_id") == 3

    def test_existing_color_rule_priority(self):
        """'有哪些红色光纤' still matches R020 (colored_query)."""
        result = RuleEngine.match("有哪些红色光纤")
        assert result is not None
        assert result.intent == "colored_query"
        assert result.params.get("color") == "RED"

    def test_existing_analysis_rule(self):
        """'分析光纤3' still matches spanloss_analysis."""
        result = RuleEngine.match("分析光纤3")
        assert result is not None
        assert result.intent == "spanloss_analysis"
        assert result.fast_path_eligible is False

    def test_no_match_unrelated(self):
        """Unrelated input still returns None."""
        result = RuleEngine.match("今天天气怎么样")
        assert result is None
