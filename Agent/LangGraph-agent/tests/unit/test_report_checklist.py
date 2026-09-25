"""报告确定性清单 + 评估器 veto 路径测试。"""

import pytest

from src.governance.report_checklist import (
    check_numbers_grounded,
    check_sections_present,
    check_severity_consistent,
    run_report_checklist,
)

# 合规故障报告样本（数字均可溯源，章节齐全）
GOOD_REPORT = """# 光纤故障分析报告

## 基本信息
- 生成时间：2026-08-14 10:30

## 一、故障描述
光纤5衰耗超标，实测 3.2dB，阈值 5.0dB。

## 二、影响范围
影响业务 2 条。

## 三、根因分析
衰耗超过阈值 5.0dB。

## 四、处理过程
已派单处理。
"""

SOURCE_SUMMARY = "spanloss=3.2dB, threshold=5.0dB, fiber_id=5, 影响业务2条"


class TestNumbersGrounded:
    def test_all_grounded(self):
        result = check_numbers_grounded(GOOD_REPORT, [SOURCE_SUMMARY])
        assert result["passed"] is True

    def test_hallucinated_number_caught(self):
        bad = GOOD_REPORT + "\n实测衰耗高达 9.9dB。\n"
        result = check_numbers_grounded(bad, [SOURCE_SUMMARY])
        assert result["passed"] is False
        assert "9.9" in result["evidence"]

    def test_date_numbers_benign(self):
        report = GOOD_REPORT + "\n生成于 2026-08-14 10:30:25。\n"
        result = check_numbers_grounded(report, [SOURCE_SUMMARY])
        assert result["passed"] is True


class TestSectionsPresent:
    def test_fault_report_complete(self):
        result = check_sections_present(GOOD_REPORT)
        assert result["passed"] is True

    def test_missing_section_caught(self):
        report = """# 光纤故障分析报告

## 基本信息
- 生成时间：2026-08-14

## 一、故障描述
描述内容。
"""
        result = check_sections_present(report)
        assert result["passed"] is False
        assert "影响" in result["evidence"] or "根因" in result["evidence"]

    def test_daily_report_type_detected(self):
        report = """# 光纤维护日报

## 基本信息
## 一、统计概览
## 二、异常光纤列表
## 三、重点分析
## 四、维护建议
"""
        result = check_sections_present(report)
        assert result["passed"] is True

    def test_generic_report(self):
        report = "# 光纤维护报告\n\n## 概要\n内容\n\n## 详细发现\n内容\n"
        result = check_sections_present(report)
        assert result["passed"] is True


class TestSeverityConsistent:
    def test_consistent(self):
        result = check_severity_consistent({"status": "WARNING"}, {"severity": "WARNING"})
        assert result["passed"] is True

    def test_inconsistent_caught(self):
        result = check_severity_consistent({"status": "CRITICAL"}, {"severity": "NORMAL"})
        assert result["passed"] is False
        assert "CRITICAL" in result["evidence"]

    def test_missing_verdict_skipped(self):
        result = check_severity_consistent({"status": "WARNING"}, {})
        assert result["passed"] is True


class TestRunChecklist:
    def test_good_report_all_pass(self):
        results = run_report_checklist(
            GOOD_REPORT,
            SOURCE_SUMMARY,
            {"status": "WARNING"},
            {"severity": "WARNING"},
        )
        assert len(results) == 3
        assert all(r["passed"] for r in results)

    def test_bad_report_reports_failure(self):
        bad = GOOD_REPORT.replace("3.2dB", "8.8dB")  # 注入幻觉数字
        results = run_report_checklist(
            bad,
            SOURCE_SUMMARY,
            {"status": "WARNING"},
            {"severity": "WARNING"},
        )
        failed = [r for r in results if not r["passed"]]
        assert any(r["check"] == "numbers_grounded" for r in failed)


class TestEvaluatorNodeVeto:
    @pytest.mark.asyncio
    async def test_checklist_veto_without_llm_call(self):
        """幻觉数字报告必须被 veto，且不调用 LLM。"""
        from unittest.mock import patch

        from src.nodes import report_evaluator as module

        bad = GOOD_REPORT.replace("3.2dB", "8.8dB")
        state = {
            "report_content": bad,
            "collected_data_summary": SOURCE_SUMMARY,
            "rule_judgment": {"status": "WARNING"},
            "analysis_verdict": {"severity": "WARNING"},
            "report_eval": {},
            "llm_call_count": 0,
        }

        with patch.object(module, "_get_chain") as mock_chain:
            updates = await module.report_evaluator_node(state)

        mock_chain.assert_not_called()  # veto 在 LLM 之前发生
        eval_result = updates["report_eval"]
        assert eval_result["passed"] is False
        assert eval_result["refinement_count"] == 1
        assert "numbers_grounded" in eval_result["feedback"]
        assert "llm_call_count" not in updates  # 未消耗 LLM 预算

    @pytest.mark.asyncio
    async def test_empty_report_passes(self):
        from src.nodes.report_evaluator import report_evaluator_node

        updates = await report_evaluator_node({"report_content": "", "report_eval": {}})
        assert updates["report_eval"]["passed"] is True

    @pytest.mark.asyncio
    async def test_llm_failure_passes_when_checklist_ok(self):
        """清单全过但 LLM 不可用 → 放行（不掩盖清单失败）。"""
        from unittest.mock import patch

        from src.nodes import report_evaluator as module

        state = {
            "report_content": GOOD_REPORT,
            "collected_data_summary": SOURCE_SUMMARY,
            "rule_judgment": {"status": "WARNING"},
            "analysis_verdict": {"severity": "WARNING"},
            "report_eval": {},
            "llm_call_count": 0,
        }

        def _raise():
            raise RuntimeError("ollama down")

        with patch.object(module, "_get_chain", side_effect=_raise):
            updates = await module.report_evaluator_node(state)

        assert updates["report_eval"]["passed"] is True
