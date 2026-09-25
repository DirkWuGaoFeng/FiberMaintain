"""
测试：工具风险评级系统 (ToolRiskRating)。
"""

from src.governance.tool_risk import (
    ToolRiskLevel,
    ToolRiskProfile,
    get_tool_risk_engine,
)


class TestRiskProfiles:
    def test_query_tools_are_low_risk(self):
        engine = get_tool_risk_engine()
        for tool in [
            "fiber_spanloss_query",
            "fiber_performance_query",
            "fiber_connection_query",
            "ne_query",
            "alarm_query",
            "knowledge_query",
        ]:
            profile = engine.get_profile(tool)
            assert profile.risk_level == ToolRiskLevel.LOW, f"{tool} should be LOW"

    def test_ticket_tools_are_high_risk(self):
        engine = get_tool_risk_engine()
        profile = engine.get_profile("pull_call_create")
        assert profile.risk_level == ToolRiskLevel.HIGH
        assert profile.confirm_required is True

        profile = engine.get_profile("pull_call_cancel")
        assert profile.risk_level == ToolRiskLevel.HIGH

    def test_export_tools_are_medium_risk(self):
        engine = get_tool_risk_engine()
        profile = engine.get_profile("export_spanloss_report")
        assert profile.risk_level == ToolRiskLevel.MEDIUM

    def test_unknown_tool_defaults_to_low(self):
        engine = get_tool_risk_engine()
        profile = engine.get_profile("unknown_tool_xyz")
        assert profile.risk_level == ToolRiskLevel.LOW


class TestDynamicRiskEvaluation:
    def test_batch_query_upgrades_with_many_fibers(self):
        engine = get_tool_risk_engine()
        params = {"fiber_ids": list(range(25))}
        level = engine.evaluate_risk("batch_spanloss_query", params)
        assert level == ToolRiskLevel.HIGH

    def test_batch_query_stays_low_with_few_fibers(self):
        engine = get_tool_risk_engine()
        params = {"fiber_ids": [1, 2, 3]}
        level = engine.evaluate_risk("batch_spanloss_query", params)
        assert level == ToolRiskLevel.MEDIUM

    def test_export_upgrades_with_all_scope(self):
        engine = get_tool_risk_engine()
        params = {"scope": "all"}
        level = engine.evaluate_risk("export_spanloss_report", params)
        assert level == ToolRiskLevel.HIGH

    def test_export_stays_medium_with_specific_scope(self):
        engine = get_tool_risk_engine()
        params = {"scope": "fiber_group_a"}
        level = engine.evaluate_risk("export_spanloss_report", params)
        assert level == ToolRiskLevel.MEDIUM


class TestConfirmationGate:
    def test_high_risk_requires_confirmation(self):
        engine = get_tool_risk_engine()
        assert engine.requires_confirmation("pull_call_create") is True

    def test_low_risk_no_confirmation(self):
        engine = get_tool_risk_engine()
        assert engine.requires_confirmation("fiber_spanloss_query") is False

    def test_dynamic_high_requires_confirmation(self):
        engine = get_tool_risk_engine()
        params = {"fiber_ids": list(range(25))}
        assert engine.requires_confirmation("batch_spanloss_query", params) is True


class TestCustomization:
    def test_register_new_profile(self):
        engine = get_tool_risk_engine()
        profile = ToolRiskProfile(
            tool_name="custom_tool",
            risk_level=ToolRiskLevel.HIGH,
            confirm_required=True,
        )
        engine.register_profile(profile)
        assert engine.get_profile("custom_tool").risk_level == ToolRiskLevel.HIGH

    def test_audit_log(self):
        engine = get_tool_risk_engine()
        log = engine.audit_log("fiber_spanloss_query", ToolRiskLevel.LOW)
        assert log["tool_name"] == "fiber_spanloss_query"
        assert log["risk_level"] == "low"
        assert "timestamp" in log
