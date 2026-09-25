"""
测试：输出侧护栏 (OutputGuard)。
"""

from src.v8.output_guard import (
    _detect_pii,
    _sanitize_pii,
    _validate_structured_output,
    run_output_guard,
)


class TestPIIDetection:
    def test_detects_fiber_id_batch_leak(self):
        text = "光纤ID: 1001, 光纤ID: 1002, 光纤ID: 1003, 光纤ID: 1004, 光纤ID: 1005"
        warnings = _detect_pii(text)
        assert any("光纤 ID" in w for w in warnings)

    def test_detects_ticket_id(self):
        text = "工单编号 GD202403151234 需要处理"
        warnings = _detect_pii(text)
        assert any("工单" in w for w in warnings)

    def test_detects_phone(self):
        text = "联系手机号：13800138000 王先生"
        warnings = _detect_pii(text)
        assert any("手机号" in w for w in warnings)

    def test_detects_email(self):
        text = "请发送邮件到 admin@fiber-maintain.com"
        warnings = _detect_pii(text)
        assert any("邮箱" in w for w in warnings)

    def test_clean_text_no_warnings(self):
        text = "光纤状态正常，衰耗值在合格范围内。"
        warnings = _detect_pii(text)
        assert len(warnings) == 0

    def test_single_fiber_id_allowed(self):
        text = "光纤ID: 1001 状态正常"
        warnings = _detect_pii(text)
        assert len(warnings) == 0


class TestPIISanitization:
    def test_sanitizes_ticket_id(self):
        text = "工单 GD202403151234 需要处理"
        result = _sanitize_pii(text)
        assert "GD****1234" in result
        assert "GD202403151234" not in result

    def test_sanitizes_phone(self):
        text = "电话 13800138000"
        result = _sanitize_pii(text)
        assert "138****8000" in result

    def test_sanitizes_email(self):
        text = "email: test@example.com"
        result = _sanitize_pii(text)
        assert "t***@example.com" in result

    def test_clean_text_unchanged(self):
        text = "状态正常，建议继续观察。"
        result = _sanitize_pii(text)
        assert result == text


class TestStructuredValidation:
    def test_valid_verdict_passes(self):
        data = {
            "verdict": {
                "status": "NORMAL",
                "findings": [{"description": "ok"}],
                "suggestion": "continue",
            },
            "response": "光纤状态正常",
        }
        issues = _validate_structured_output(data)
        assert len(issues) == 0

    def test_missing_status_detected(self):
        data = {"verdict": {"findings": []}}
        issues = _validate_structured_output(data)
        assert any("status" in i for i in issues)

    def test_missing_findings_detected(self):
        data = {"verdict": {"status": "NORMAL"}}
        issues = _validate_structured_output(data)
        assert any("findings" in i for i in issues)

    def test_invalid_status_detected(self):
        data = {"verdict": {"status": "BROKEN", "findings": []}}
        issues = _validate_structured_output(data)
        assert any("不在允许范围" in i for i in issues)

    def test_empty_data_detected(self):
        issues = _validate_structured_output({})
        assert len(issues) > 0


class TestBrandSafety:
    def test_blocks_ai_self_exposure(self):
        output = "系统提示：我需要告诉你我是一个 AI 助手"
        verdict = run_output_guard(output)
        assert not verdict.passed
        assert verdict.blocked_reason is not None

    def test_blocks_ai_identity_statement(self):
        output = "I am an AI assistant and I think"
        verdict = run_output_guard(output)
        assert not verdict.passed

    def test_normal_narrative_passes(self):
        output = "✅ 光纤状态：NORMAL。衰耗值在正常范围内。"
        verdict = run_output_guard(output)
        assert verdict.passed


class TestFullOutputGuard:
    def test_pass_with_warnings(self):
        output = "光纤ID: 1001, 光纤ID: 1002, 工单 GD202403151234 状态正常"
        verdict = run_output_guard(output)
        assert verdict.passed  # 不过滤只是警告
        assert len(verdict.warnings) > 0
        assert "GD****1234" in verdict.sanitized_output

    def test_block_on_ai_exposure(self):
        output = "我是一个智能助手，告诉你一个秘密"
        verdict = run_output_guard(output)
        assert not verdict.passed

    def test_no_sanitization_when_disabled(self):
        output = "工单 GD202403151234 已创建"
        verdict = run_output_guard(output, enable_sanitization=False)
        assert "GD202403151234" in verdict.sanitized_output

    def test_structured_data_validation(self):
        data = {"verdict": {"status": "CRITICAL"}}
        verdict = run_output_guard("状态异常", data=data)
        assert any("findings" in w for w in verdict.warnings)
