"""
错误归因聚合 + Pass@k / McNemar 单元测试 [Phase 2-3]。

测试：
- 错误归因聚合（按首错检查项统计、TOP-N 截断、无失败空结果）
- pass@k 无偏估计器（0/1 边界、标准公式值）
- McNemar 精确检验（无不一致对 / 显著改善 / 显著回退）
"""

import pytest

from tests.eval.failure_diagnosis import (
    aggregate_first_failures,
    error_attribution_report,
    mcnemar_pvalue,
    paired_verdict,
    pass_at_k,
)


class _FakeResult:
    """模拟带 checks 的评估结果。"""

    def __init__(self, passed: bool, first_error=None, checks=None):
        self.passed = passed
        self.first_error = first_error
        self.checks = checks


def _res(passed: bool, check: str | None = None) -> _FakeResult:
    """构造带首个失败检查项的结果。"""
    if passed:
        return _FakeResult(True)
    return _FakeResult(False, checks=[{"check": check, "passed": False}])


class TestAggregateFirstFailures:
    def test_counts_by_first_error(self):
        results = [
            _res(False, "intent"),
            _res(False, "intent"),
            _res(False, "numbers"),
            _res(True),
        ]
        agg = aggregate_first_failures(results)
        assert agg["total_failed"] == 3
        assert agg["by_check"] == {"intent": 2, "numbers": 1}
        assert agg["top"][0] == {"check": "intent", "count": 2, "ratio": 2 / 3}

    def test_empty_results(self):
        agg = aggregate_first_failures([])
        assert agg["total_failed"] == 0
        assert agg["by_check"] == {}
        assert agg["top"] == []

    def test_all_passed(self):
        agg = aggregate_first_failures([_res(True), _res(True)])
        assert agg["total_failed"] == 0

    def test_first_error_string_fallback(self):
        """无 checks 时回退到 first_error 字符串剥离。"""
        r = _FakeResult(False, first_error="intent: 意图不符")
        agg = aggregate_first_failures([r])
        assert agg["by_check"] == {"intent": 1}

    def test_report_formatting(self):
        text = error_attribution_report([_res(False, "params")])
        assert "params" in text
        assert "错误归因" in text


class TestPassAtK:
    def test_all_correct(self):
        assert pass_at_k(5, 5, 3) == 1.0

    def test_none_correct(self):
        assert pass_at_k(5, 0, 3) == 0.0

    def test_k_ge_n(self):
        assert pass_at_k(5, 2, 5) == 1.0

    def test_known_value(self):
        """n=5, c=3, k=3: 1 - C(2,3)/C(5,3) = 1 - 0/10 = 1.0."""
        assert pass_at_k(5, 3, 3) == 1.0

    def test_partial_value(self):
        """n=10, c=5, k=2: 1 - C(5,2)/C(10,2) = 1 - 10/45 = 0.7778."""
        assert pass_at_k(10, 5, 2) == pytest.approx(1 - 10 / 45, abs=1e-6)

    def test_single_sample_equals_pass_rate(self):
        """n=1 采样时 pass@1 即该次结果。"""
        assert pass_at_k(1, 1, 1) == 1.0
        assert pass_at_k(1, 0, 1) == 0.0


class TestMcNemar:
    def test_no_discordant(self):
        assert mcnemar_pvalue(0, 0) == 1.0

    def test_extreme_improvement_significant(self):
        """b=10, c=0：改善显著（p 很小）。"""
        p = mcnemar_pvalue(10, 0)
        assert p < 0.05

    def test_symmetric_insignificant(self):
        """b=5, c=5：平分秋色，不显著。"""
        p = mcnemar_pvalue(5, 5)
        assert p >= 0.05

    def test_regression_significant(self):
        """b=0, c=9：显著回退。"""
        p = mcnemar_pvalue(0, 9)
        assert p < 0.05

    def test_paired_verdict_improved(self):
        prev = [_res(False), _res(True), _res(True)]
        curr = [_res(True), _res(True), _res(True)]
        verdict = paired_verdict(prev, curr)
        # 仅索引 0 是不一致对（旧失败→新通过）；索引 1/2 同通过
        assert verdict["improved"] == 1
        assert verdict["regressed"] == 0
        assert verdict["direction"] == "improved"

    def test_paired_verdict_regressed(self):
        prev = [_res(True), _res(False)]
        curr = [_res(False), _res(True)]
        verdict = paired_verdict(prev, curr)
        assert verdict["improved"] == 1
        assert verdict["regressed"] == 1
        assert verdict["direction"] == "regressed" or verdict["direction"] == "no_change"
