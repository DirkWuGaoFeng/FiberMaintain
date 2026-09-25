"""
测试：Agent 级熔断器 (AgentCircuitBreaker)。
"""

from src.resilience.agent_circuit_breaker import (
    AgentCircuitBreaker,
    get_agent_circuit_breaker,
)


class TestCircuitBreakerDetection:
    def test_detects_analysis_loop(self):
        cb = AgentCircuitBreaker(max_analysis_loops=3)
        cb.record_analysis_result(needs_more_data=True, data_signature="sig_1")
        cb.record_analysis_result(needs_more_data=True, data_signature="sig_2")
        cb.record_analysis_result(needs_more_data=True, data_signature="sig_3")

        verdict = cb.check()
        assert verdict.should_terminate is True
        assert verdict.reason == "analysis_loop_detected"

    def test_detects_no_progress(self):
        cb = AgentCircuitBreaker(max_no_progress_loops=3)
        cb.record_analysis_result(needs_more_data=False, data_signature="same")
        cb.record_analysis_result(needs_more_data=False, data_signature="same")
        cb.record_analysis_result(needs_more_data=False, data_signature="same")
        cb.record_analysis_result(needs_more_data=False, data_signature="same")

        verdict = cb.check()
        assert verdict.should_terminate is True
        assert verdict.reason == "no_progress"

    def test_detects_llm_budget_exhausted(self):
        cb = AgentCircuitBreaker(max_llm_budget=3)
        for _ in range(3):
            cb.record_llm_call()

        verdict = cb.check()
        assert verdict.should_terminate is True
        assert verdict.reason == "llm_budget_exhausted"

    def test_normal_progress_does_not_trigger(self):
        cb = AgentCircuitBreaker(max_analysis_loops=3, max_no_progress_loops=3)
        # 交替进展
        cb.record_analysis_result(needs_more_data=True, data_signature="sig_1")
        cb.record_analysis_result(needs_more_data=False, data_signature="sig_2")
        cb.record_analysis_result(needs_more_data=True, data_signature="sig_3")

        verdict = cb.check()
        assert verdict.should_terminate is False

    def test_data_signature_change_resets_progress(self):
        cb = AgentCircuitBreaker(max_no_progress_loops=3)
        cb.record_analysis_result(False, data_signature="A")
        cb.record_analysis_result(False, data_signature="A")
        cb.record_analysis_result(False, data_signature="B")  # 签名变化！

        verdict = cb.check()
        assert verdict.should_terminate is False


class TestCircuitBreakerRecovery:
    def test_consecutive_counter_resets_on_success(self):
        cb = AgentCircuitBreaker(max_analysis_loops=3)
        cb.record_analysis_result(True, "sig_1")
        cb.record_analysis_result(True, "sig_2")
        cb.record_analysis_result(False, "sig_3")  # 成功，重置

        verdict = cb.check()
        assert not verdict.should_terminate
        assert cb._consecutive_needs_more_data == 0

    def test_reset_clears_all_state(self):
        cb = AgentCircuitBreaker()
        cb.record_analysis_result(True, "sig_1")
        cb.record_llm_call()
        cb.reset()

        assert cb.loop_count == 0
        assert cb.llm_calls == 0
        verdict = cb.check()
        assert not verdict.should_terminate


class TestDegradedResult:
    def test_generates_degraded_result(self):
        cb = AgentCircuitBreaker()
        result = cb.get_degraded_result("analysis_loop_detected", {"fiber_1": "normal"})

        assert result["status"] == "DEGRADED"
        assert result["degradation_reason"] == "analysis_loop_detected"
        assert result["metadata"]["circuit_breaker_triggered"] is True
        assert "fiber_1" in result["partial_data"]


class TestSingleton:
    def test_get_breaker_returns_same_instance(self):
        cb1 = get_agent_circuit_breaker()
        cb2 = get_agent_circuit_breaker()
        assert cb1 is cb2
