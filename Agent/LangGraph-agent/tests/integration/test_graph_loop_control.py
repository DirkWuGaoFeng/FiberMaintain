"""
Integration tests for Main Graph — Loop Control [v7.1].

Tests the four termination safeguards:
  ① Round limit (≤3)
  ② LLM budget (≤10)
  ③ No-progress detection
  ④ Tool all-fail circuit breaker

Uses routing functions directly with constructed states.
"""

import pytest

from src.graph.routing import route_after_analysis, compute_action_signature


class TestRoundLimitSafeguard:
    """Safeguard ①: Round limit termination."""

    def test_loop_continues_below_limit(self):
        """Loop continues when loop_count < max_loops."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x", "reason": "need history"}},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 2,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
        }
        assert route_after_analysis(state) == "need_more_data"

    def test_loop_stops_at_limit(self):
        """Loop terminates when loop_count >= max_loops."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 3,
            "max_loops": 3,
            "llm_call_count": 3,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "single_query",
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"
        assert result == "direct_narrate"

    def test_loop_stops_above_limit(self):
        """Loop terminates when loop_count > max_loops (edge case)."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 5,
            "max_loops": 3,
            "llm_call_count": 5,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "spanloss_query",
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"


class TestLLMBudgetSafeguard:
    """Safeguard ②: LLM call budget termination."""

    def test_loop_continues_below_budget(self):
        """Loop continues when llm_call_count < max_llm_calls."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "y"}},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 5,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
        }
        assert route_after_analysis(state) == "need_more_data"

    def test_loop_stops_at_budget(self):
        """Loop terminates when llm_call_count >= max_llm_calls."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "y"}},
            "loop_count": 2,
            "max_loops": 3,
            "llm_call_count": 10,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "trend_analysis",
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"
        assert result == "generate_report"  # trend_analysis → report

    def test_budget_exceeded_forces_exit(self):
        """Even with need_more_data=True, budget forces exit."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "z", "reason": "more"}},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 15,  # Way over budget
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "single_query",
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"


class TestNoProgressSafeguard:
    """Safeguard ③: No-progress detection."""

    def test_loop_continues_with_progress(self):
        """Loop continues when no_progress_count < 2."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 2,
            "max_llm_calls": 10,
            "no_progress_count": 1,
            "degradation_level": 0,
        }
        assert route_after_analysis(state) == "need_more_data"

    def test_loop_stops_on_no_progress(self):
        """Loop terminates when no_progress_count >= 2."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 2,
            "max_llm_calls": 10,
            "no_progress_count": 2,
            "intent": "spanloss_analysis",
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"

    def test_action_signature_detects_repeat(self):
        """Same action+observation produces same signature (no progress)."""
        sig1 = compute_action_signature("fiber_spanloss_query", "spanloss=3.2dB")
        sig2 = compute_action_signature("fiber_spanloss_query", "spanloss=3.2dB")
        assert sig1 == sig2  # Same = no progress

    def test_action_signature_detects_new_info(self):
        """Different observation produces different signature (progress)."""
        sig1 = compute_action_signature("fiber_spanloss_query", "spanloss=3.2dB")
        sig2 = compute_action_signature("fiber_history_performance", "history data...")
        assert sig1 != sig2  # Different = progress made


class TestToolAllFailSafeguard:
    """Safeguard ④: Tool all-fail circuit breaker."""

    def test_all_errors_triggers_degraded(self):
        """All lines containing error → degraded."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
            "collected_data_summary": "错误: 连接超时\nerror: timeout\n错误: 服务不可用",
        }
        assert route_after_analysis(state) == "degraded"

    def test_mixed_results_not_degraded(self):
        """Some success + some errors → NOT degraded."""
        state = {
            "analysis_verdict": {"need_more_data": False, "severity": "NORMAL"},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
            "collected_data_summary": "spanloss=3.2dB, OOP=-3.5\n错误: 告警查询失败",
            "intent": "single_query",
        }
        result = route_after_analysis(state)
        assert result != "degraded"

    def test_empty_summary_not_degraded(self):
        """Empty data summary should not trigger degraded."""
        state = {
            "analysis_verdict": {"need_more_data": False, "severity": "NORMAL"},
            "loop_count": 0,
            "max_loops": 3,
            "llm_call_count": 1,
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "degradation_level": 0,
            "collected_data_summary": "",
            "intent": "single_query",
        }
        result = route_after_analysis(state)
        assert result != "degraded"


class TestSafeguardPriority:
    """Test that safeguards are checked in correct priority order."""

    def test_degradation_takes_highest_priority(self):
        """Degradation check happens before all other safeguards."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 0,  # Below limit
            "max_loops": 3,
            "llm_call_count": 0,  # Below budget
            "max_llm_calls": 10,
            "no_progress_count": 0,  # No progress issue
            "degradation_level": 3,  # But degraded!
        }
        assert route_after_analysis(state) == "degraded"

    def test_round_limit_before_llm_budget(self):
        """Round limit is checked before LLM budget."""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 3,  # At round limit
            "max_loops": 3,
            "llm_call_count": 10,  # Also at LLM budget
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "single_query",
        }
        # Both trigger, but should still exit (not need_more_data)
        result = route_after_analysis(state)
        assert result != "need_more_data"
