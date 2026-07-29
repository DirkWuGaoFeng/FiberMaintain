"""State 定义单元测试"""

import pytest
from src.graph.state import IntentResult, AnalysisResult


class TestIntentResult:
    """意图识别结果测试"""

    def test_valid_single_query(self):
        result = IntentResult(
            intent="single_query",
            confidence=0.9,
            fiber_ids=["FIB-001"],
            reasoning="用户查询单根光纤",
        )
        assert result.intent == "single_query"
        assert result.confidence == 0.9

    def test_valid_batch_query(self):
        result = IntentResult(
            intent="batch_query",
            confidence=0.8,
            fiber_ids=["FIB-001", "FIB-002"],
            reasoning="用户批量查询",
        )
        assert result.intent == "batch_query"

    def test_all_intents_valid(self):
        valid_intents = [
            "single_query", "batch_query", "spanloss_analysis",
            "color_diagnosis", "trend_analysis", "health_check",
            "report_generation", "knowledge_qa", "chitchat",
        ]
        for intent in valid_intents:
            result = IntentResult(intent=intent, confidence=0.5, reasoning="test")
            assert result.intent == intent

    def test_invalid_intent_rejected(self):
        with pytest.raises(Exception):
            IntentResult(intent="invalid_intent", confidence=0.5, reasoning="test")


class TestAnalysisResult:
    """分析结论测试"""

    def test_basic_analysis(self):
        result = AnalysisResult(
            summary="测试分析",
            severity="warning",
            confidence=0.8,
        )
        assert result.severity == "warning"
        assert result.anomalies == []
        assert result.recommendations == []
