"""
主图集成测试 — 循环控制 [v7.1]。

测试四类终止保护：
  ① 轮数限制（≤3）
  ② LLM 预算（≤10）
  ③ 无进展检测
  ④ 工具全部失败熔断器

直接使用路由函数配合构造的状态进行测试。
"""

from src.graph.routing import compute_action_signature, route_after_analysis


class TestRoundLimitSafeguard:
    """保护 ①：轮数限制终止。"""

    def test_loop_continues_below_limit(self):
        """当 loop_count < max_loops 时循环继续。"""
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
        """当 loop_count >= max_loops 时循环终止。"""
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
        """当 loop_count > max_loops 时循环终止（边界情况）。"""
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
    """保护 ②：LLM 调用预算终止。"""

    def test_loop_continues_below_budget(self):
        """当 llm_call_count < max_llm_calls 时循环继续。"""
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
        """当 llm_call_count >= max_llm_calls 时循环终止。"""
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
        """即使 need_more_data=True，预算仍强制退出。"""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "z", "reason": "more"}},
            "loop_count": 1,
            "max_loops": 3,
            "llm_call_count": 15,  # 远超预算
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "single_query",
        }
        result = route_after_analysis(state)
        assert result != "need_more_data"


class TestNoProgressSafeguard:
    """保护 ③：无进展检测。"""

    def test_loop_continues_with_progress(self):
        """当 no_progress_count < 2 时循环继续。"""
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
        """当 no_progress_count >= 2 时循环终止。"""
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
        """相同动作+观察产生相同签名（无进展）。"""
        sig1 = compute_action_signature("fiber_spanloss_query", "spanloss=3.2dB")
        sig2 = compute_action_signature("fiber_spanloss_query", "spanloss=3.2dB")
        assert sig1 == sig2  # 相同 = 无进展

    def test_action_signature_detects_new_info(self):
        """不同观察产生不同签名（有进展）。"""
        sig1 = compute_action_signature("fiber_spanloss_query", "spanloss=3.2dB")
        sig2 = compute_action_signature("fiber_history_performance", "history data...")
        assert sig1 != sig2  # 不同 = 已取得进展


class TestToolAllFailSafeguard:
    """保护 ④：工具全部失败熔断器。"""

    def test_all_errors_triggers_degraded(self):
        """所有行都含错误 → 降级。"""
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
        """部分成功 + 部分错误 → 不降级。"""
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
        """空数据摘要不应触发降级。"""
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
    """测试保护按正确的优先级顺序检查。"""

    def test_degradation_takes_highest_priority(self):
        """降级检查先于所有其他保护。"""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 0,  # 低于上限
            "max_loops": 3,
            "llm_call_count": 0,  # 低于预算
            "max_llm_calls": 10,
            "no_progress_count": 0,  # 无进展问题
            "degradation_level": 3,  # 但已降级！
        }
        assert route_after_analysis(state) == "degraded"

    def test_round_limit_before_llm_budget(self):
        """轮数限制先于 LLM 预算检查。"""
        state = {
            "analysis_verdict": {"need_more_data": True, "additional_query": {"tool": "x"}},
            "loop_count": 3,  # 已达到轮数上限
            "max_loops": 3,
            "llm_call_count": 10,  # 同时也达到 LLM 预算
            "max_llm_calls": 10,
            "no_progress_count": 0,
            "intent": "single_query",
        }
        # 两者都触发，但仍应退出（不返回 need_more_data）
        result = route_after_analysis(state)
        assert result != "need_more_data"
