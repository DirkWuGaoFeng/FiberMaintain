"""ToolReviewer 单测（书籍 Ch4：提案者-审核者分离）。"""

from src.security.tool_reviewer import get_tool_reviewer


class TestReviewer:
    def setup_method(self):
        self.reviewer = get_tool_reviewer()

    def test_low_risk_skipped(self):
        # 低风险只读查询 → 跳过复核，直接 allow
        result = self.reviewer.review("fiber_spanloss_query", {"fiber_id": 5})
        assert result.is_allow
        assert "跳过" in result.reason

    def test_high_risk_legit_params(self):
        # 高风险工单取消，参数合法
        result = self.reviewer.review("pull_call_cancel", {"ticket_id": "T123", "reason": "用户取消"})
        assert result.is_allow

    def test_high_risk_empty_params(self):
        # 高风险操作缺少参数 → block
        result = self.reviewer.review("pull_call_cancel", {})
        assert not result.is_allow
        assert len(result.violations) > 0

    def test_param_type_mismatch(self):
        # 参数类型错误（ticket_id 应为 id 类型= int/str，但给 list）
        result = self.reviewer.review("pull_call_cancel", {"ticket_id": [1, 2, 3], "reason": "test"})
        assert not result.is_allow
        assert any("ticket_id" in v for v in result.violations)

    def test_unknown_tool_default_low(self):
        # 未注册工具默认低风险 → 跳过复核
        result = self.reviewer.review("some_new_tool", {"x": 1})
        assert result.is_allow


class TestPullCallReviewerIntegration:
    """tool_reviewer 插入 pullcall_tools 确认前 [v7.4]."""

    def test_pull_call_create_legit_params_allowed(self, monkeypatch):
        """合法参数 → 通过复核，进入确认门禁."""
        import json

        from src.tools.pullcall_tools import pull_call_create

        class FakeGate:
            def request(self, operation, params, description):
                return {"token": "tk-1", "operation": operation, "params": params}

        monkeypatch.setattr(
            "src.tools.pullcall_tools.get_confirmation_gate",
            lambda: FakeGate(),
        )

        async def _run():
            return await pull_call_create.ainvoke({"fiber_id": 1001, "test_type": "OTDR", "priority": "NORMAL"})

        import asyncio

        result = asyncio.run(_run())
        data = json.loads(result)
        assert data["status"] == "pending_confirmation"
        assert data["confirm_token"] == "tk-1"

    def test_pull_call_create_invalid_type_blocked(self, monkeypatch):
        """类型越界参数 → 复核 block，不进入确认门禁."""
        import json

        from src.tools.pullcall_tools import _pending_confirmation_json

        # 若复核通过会进入 gate，用会抛异常的 gate 验证不会走到
        class BoomGate:
            def request(self, operation, params, description):
                raise AssertionError("不应进入确认门禁")

        monkeypatch.setattr(
            "src.tools.pullcall_tools.get_confirmation_gate",
            lambda: BoomGate(),
        )

        # ticket_id 为 list → 类型违规（应为 int/str），reviewer 应 block
        result = _pending_confirmation_json(
            "pull_call_cancel",
            {"ticket_id": [1, 2, 3], "reason": "test"},
            "取消拉纤会话",
        )
        data = json.loads(result)
        assert data.get("error_code") == "REVIEW_BLOCKED"
