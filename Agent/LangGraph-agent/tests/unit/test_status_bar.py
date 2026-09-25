"""状态栏（build_status_bar）确定性派生测试。"""

from src.nodes.status_bar import build_status_bar


class TestStatusBarBasics:
    def test_empty_state_defaults(self):
        bar = build_status_bar({})
        assert "第 0/3 轮" in bar
        assert "LLM 调用 0/10" in bar
        assert "已请求数据的工具: 无" in bar
        assert "已失败操作: 无" in bar
        assert "尚未收集" in bar
        assert "停滞警告" not in bar

    def test_budget_reflects_state(self):
        state = {"loop_count": 2, "max_loops": 3, "llm_call_count": 7, "max_llm_calls": 10}
        bar = build_status_bar(state)
        assert "第 2/3 轮" in bar
        assert "LLM 调用 7/10" in bar


class TestToolHistory:
    def test_tools_deduped_in_order(self):
        state = {
            "loop_history": [
                {"tool_requested": "query_spanloss"},
                {"tool_requested": "query_alarms"},
                {"tool_requested": "query_spanloss"},
            ]
        }
        bar = build_status_bar(state)
        assert "已请求数据的工具: query_spanloss, query_alarms" in bar

    def test_unknown_tool_skipped(self):
        state = {"loop_history": [{"tool_requested": "unknown"}]}
        bar = build_status_bar(state)
        assert "已请求数据的工具: 无" in bar


class TestFailures:
    def test_error_entries_listed(self):
        state = {
            "audit_trail": [
                {"node": "data_collector", "action": "error", "error": "timeout after 5s"},
                {"node": "rule_judgment", "action": "threshold_check"},  # 无 error，忽略
            ]
        }
        bar = build_status_bar(state)
        assert "已失败操作: data_collector: timeout after 5s" in bar

    def test_long_error_truncated(self):
        state = {"audit_trail": [{"node": "n", "error": "x" * 200}]}
        bar = build_status_bar(state)
        assert "x" * 60 in bar
        assert "x" * 61 not in bar


class TestDataStatus:
    def test_available_summary(self):
        bar = build_status_bar({"collected_data_summary": "spanloss=0.3dB"})
        assert "可用（摘要 14 字符）" in bar

    def test_error_summary_detected(self):
        bar = build_status_bar({"collected_data_summary": "数据采集失败：连接超时"})
        assert "采集失败" in bar

    def test_query_failure_prefix_detected(self):
        bar = build_status_bar({"collected_data_summary": "查询失败：500"})
        assert "采集失败" in bar


class TestNoProgressWarning:
    def test_warning_emitted(self):
        bar = build_status_bar({"no_progress_count": 2})
        assert "停滞警告" in bar
        assert "已连续 2 轮" in bar

    def test_no_warning_when_zero(self):
        bar = build_status_bar({"no_progress_count": 0})
        assert "停滞警告" not in bar
