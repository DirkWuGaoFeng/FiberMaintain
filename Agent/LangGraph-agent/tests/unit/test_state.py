"""State 定义单元测试 [v7.1]"""

import pytest
from src.graph.state import (
    IntentResult,
    AnalysisVerdict,
    RuleJudgment,
    NormalizedParams,
    LoopRecord,
    create_initial_state,
)


class TestIntentResult:
    """意图识别结果测试"""

    def test_valid_single_query(self):
        result = IntentResult(
            intent="single_query",
            confidence=0.9,
            fiber_ids=["1"],
        )
        assert result.intent == "single_query"
        assert result.confidence == 0.9

    def test_valid_batch_query(self):
        result = IntentResult(
            intent="batch_query",
            confidence=0.8,
            fiber_ids=["1", "2"],
        )
        assert result.intent == "batch_query"

    def test_all_intents_valid(self):
        valid_intents = [
            "single_query", "batch_query", "spanloss_analysis",
            "color_diagnosis", "trend_analysis", "health_check",
            "report_generation", "knowledge_qa", "chitchat",
        ]
        for intent in valid_intents:
            result = IntentResult(intent=intent, confidence=0.5)
            assert result.intent == intent

    def test_invalid_intent_rejected(self):
        with pytest.raises(Exception):
            IntentResult(intent="invalid_intent", confidence=0.5)


class TestAnalysisVerdict:
    """分析结论测试 [v7.1]"""

    def test_basic_verdict(self):
        result = AnalysisVerdict(
            conclusion="光纤衰耗超标",
            severity="WARNING",
            evidence=["spanloss=6.5dB"],
            confidence=0.8,
            need_more_data=False,
        )
        assert result.severity == "WARNING"
        assert result.need_more_data is False

    def test_need_more_data(self):
        result = AnalysisVerdict(
            conclusion="数据不足",
            severity="NORMAL",
            confidence=0.3,
            need_more_data=True,
            additional_query={"reason": "需要历史数据", "tool": "fiber_history_performance"},
        )
        assert result.need_more_data is True
        assert result.additional_query is not None


class TestRuleJudgment:
    """规则判断测试 [v7.1]"""

    def test_normal_status(self):
        judgment = RuleJudgment(
            status="NORMAL",
            findings=["所有指标正常"],
            metrics={"spanloss": 2.1},
        )
        assert judgment.status == "NORMAL"

    def test_critical_status(self):
        judgment = RuleJudgment(
            status="CRITICAL",
            findings=["衰耗超标"],
            metrics={"spanloss": 9.5},
            suggested_actions=["立即检修"],
        )
        assert judgment.status == "CRITICAL"
        assert len(judgment.suggested_actions) > 0


class TestNormalizedParams:
    """参数规范化测试"""

    def test_basic_params(self):
        params = NormalizedParams(fiber_ids=[1, 2, 3], color="RED")
        assert params.fiber_ids == [1, 2, 3]
        assert params.color == "RED"

    def test_invalid_color_rejected(self):
        with pytest.raises(Exception):
            NormalizedParams(color="BLUE")


class TestCreateInitialState:
    """初始状态工厂测试"""

    def test_basic_creation(self):
        state = create_initial_state("查询光纤1的衰耗")
        assert state["user_input"] == "查询光纤1的衰耗"
        assert state["loop_count"] == 0
        assert state["llm_call_count"] == 0
        assert state["degradation_level"] == 0
        assert state["processing_path"] == "normal"
        assert len(state["messages"]) == 1

    def test_thread_id_generation(self):
        state = create_initial_state("test")
        assert state["thread_id"] != ""
        assert state["request_id"] != ""
