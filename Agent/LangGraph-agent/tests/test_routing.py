"""
Unit tests for Routing functions [v7.1].

Tests:
- route_after_rule_engine (3-way)
- route_after_param_gate (2-way)
- route_by_intent (5-way)
- route_after_analysis (4-way + termination safeguards)
- route_after_narrator_validation (2-way)
- route_after_evaluation (2-way)
- compute_action_signature
"""

import pytest

from src.graph.routing import (
    compute_action_signature,
    route_after_analysis,
    route_after_narrator_validation,
    route_after_param_gate,
    route_after_rule_engine,
    route_by_intent,
)


class TestRouteAfterRuleEngine:
    """Test rule engine routing."""

    def test_fast_path(self):
        state = {"rule_match": {"fast_path_eligible": True, "confidence": 0.95}}
        assert route_after_rule_engine(state) == "fast_path"

    def test_rule_hit_complex(self):
        state = {"rule_match": {"fast_path_eligible": False, "confidence": 0.85}}
        assert route_after_rule_engine(state) == "rule_hit_complex"

    def test_rule_miss(self):
        state = {"rule_match": None}
        assert route_after_rule_engine(state) == "rule_miss"

    def test_low_confidence_miss(self):
        """Low confidence match still routes to rule_hit_complex (confidence handled in rule_engine)."""
        state = {"rule_match": {"fast_path_eligible": False, "confidence": 0.3}}
        # Rule engine handles confidence internally; routing just checks match existence
        assert route_after_rule_engine(state) == "rule_hit_complex"


class TestRouteAfterParamGate:
    """Test param gate routing."""

    def test_params_ok(self):
        state = {"normalized_params": {"fiber_ids": [1], "parse_failures": []}}
        assert route_after_param_gate(state) == "params_ok"

    def test_need_clarification(self):
        state = {"normalized_params": {"fiber_ids": [], "parse_failures": ["缺少光纤ID"]}}
        assert route_after_param_gate(state) == "need_clarification"


class TestRouteByIntent:
    """Test intent routing."""

    def test_data_query(self):
        state = {"intent": "single_query"}
        assert route_by_intent(state) == "data_query"

    def test_batch_query(self):
        state = {"intent": "batch_query"}
        assert route_by_intent(state) == "batch_query"

    def test_knowledge_qa(self):
        state = {"intent": "knowledge_qa"}
        assert route_by_intent(state) == "knowledge_qa"

    def test_report(self):
        state = {"intent": "report_generation"}
        assert route_by_intent(state) == "report"

    def test_chitchat(self):
        state = {"intent": "chitchat"}
        assert route_by_intent(state) == "chitchat"


class TestRouteAfterAnalysis:
    """Test analysis routing with four termination safeguards."""

    def test_need_more_data(self):
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
        }
        assert route_after_analysis(state) == "need_more_data"

    def test_loop_limit_reached(self):
        state = {
            "analysis_verdict": {"need_more_data": True},
            "loop_count": 3,
            "max_loops": 3,
            "llm_call_count": 3,
            "max_llm_calls": 10,
            "no_progress_count": 0,
        }
        # Should NOT return need_more_data
        result = route_after_analysis(state)
        assert result != "need_more_data"

    def test_llm_budget_exhausted(self):
        state = {
            "analysis_verdict": {"need_more_data": True},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 10,
            "max_llm_calls": 10,
            "no_progress_count": 0,
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"

    def test_no_progress_detection(self):
        state = {
            "analysis_verdict": {"need_more_data": True},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 2,
            "max_llm_calls": 10,
            "no_progress_count": 2,
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"

    def test_direct_narrate(self):
        state = {
            "analysis_verdict": {"need_more_data": False, "severity": "WARNING"},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "spanloss_analysis",
        }
        result = route_after_analysis(state)
        assert result in ("direct_narrate", "generate_report")


class TestRouteAfterNarratorValidation:
    """Test narrator validation routing."""

    def test_pass(self):
        state = {"narrator_validation_passed": True}
        assert route_after_narrator_validation(state) == "pass"

    def test_fail(self):
        state = {"narrator_validation_passed": False}
        assert route_after_narrator_validation(state) == "fail"


class TestRouteAfterAnalysisDegradation:
    """Test degradation and tool-fail paths in analysis routing."""

    def test_degradation_level_2_forces_degraded(self):
        """Degradation >= 2 should force 'degraded' path regardless of verdict."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 2,
        }
        assert route_after_analysis(state) == "degraded"

    def test_degradation_level_4_forces_degraded(self):
        """Degradation level 4 (offline) forces degraded."""
        state = {
            "analysis_verdict": None,
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 0,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 4,
        }
        assert route_after_analysis(state) == "degraded"

    def test_tool_all_fail_circuit_breaker(self):
        """All tool calls failed → degraded path."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
            "collected_data_summary": "错误: 连接超时\nerror: connection refused",
        }
        assert route_after_analysis(state) == "degraded"

    def test_partial_tool_failure_not_degraded(self):
        """Partial failures (some success) should NOT trigger degraded."""
        state = {
            "analysis_verdict": {"need_more_data": False, "severity": "NORMAL"},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
            "collected_data_summary": "spanloss=3.2dB\n错误: 告警查询超时",
            "intent": "single_query",
        }
        result = route_after_analysis(state)
        assert result != "degraded"


class TestRouteAfterEvaluation:
    """Test report evaluation reflection routing."""

    def test_pass_when_evaluation_passed(self):
        from src.graph.routing import route_after_evaluation
        state = {"report_eval": {"passed": True, "refinement_count": 0}}
        assert route_after_evaluation(state) == "pass"

    def test_refine_when_not_passed(self):
        from src.graph.routing import route_after_evaluation
        state = {"report_eval": {"passed": False, "refinement_count": 0}}
        assert route_after_evaluation(state) == "refine"

    def test_force_pass_after_one_refinement(self):
        from src.graph.routing import route_after_evaluation
        state = {"report_eval": {"passed": False, "refinement_count": 1}}
        assert route_after_evaluation(state) == "pass"

    def test_empty_eval_defaults_pass(self):
        from src.graph.routing import route_after_evaluation
        state = {"report_eval": {}}
        assert route_after_evaluation(state) == "pass"


class TestExitLoopIntentRouting:
    """Test _exit_loop intent-based routing decisions."""

    def test_simple_intent_direct_narrate(self):
        """Simple query intents should exit to direct_narrate."""
        state = {
            "analysis_verdict": {"need_more_data": False, "severity": "NORMAL"},
            "loop_count": 3,
            "max_loops": 3,
            "llm_call_count": 3,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "spanloss_query",
        }
        assert route_after_analysis(state) == "direct_narrate"

    def test_complex_intent_generate_report(self):
        """Complex analysis intents should exit to generate_report."""
        state = {
            "analysis_verdict": {"need_more_data": False, "severity": "WARNING"},
            "loop_count": 3,
            "max_loops": 3,
            "llm_call_count": 3,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "trend_analysis",
        }
        assert route_after_analysis(state) == "generate_report"


class TestComputeActionSignature:
    """Test action signature computation."""

    def test_deterministic(self):
        sig1 = compute_action_signature("tool_a", "observation_1")
        sig2 = compute_action_signature("tool_a", "observation_1")
        assert sig1 == sig2

    def test_different_inputs(self):
        sig1 = compute_action_signature("tool_a", "observation_1")
        sig2 = compute_action_signature("tool_b", "observation_2")
        assert sig1 != sig2

    def test_truncation_at_500_chars(self):
        """Observation longer than 500 chars is truncated for hashing."""
        long_obs = "x" * 1000
        sig = compute_action_signature("tool", long_obs)
        # Same result with truncated input
        sig2 = compute_action_signature("tool", "x" * 500)
        assert sig == sig2
