"""
自动化评估运行器 (EvalRunner).

【设计原则】
对应 AI Agent 设计原则 Chapter 6 系统级验证：
  - 自动化评估环境
  - 可追踪指标（准确率、延迟）
  - 回归门禁

【评估指标】
1. intent_accuracy: 意图分类准确率
2. injection_block_rate: 注入拦截率
3. param_fidelity: 参数保真度
4. response_latency_p50/p95: 响应延迟
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CaseResult(BaseModel):
    """单个用例评估结果."""

    case_id: str
    case_type: str = "normal"
    passed: bool = False
    intent_correct: bool = False
    injection_blocked: Optional[bool] = None
    params_match: Optional[bool] = None
    latency_ms: float = 0.0
    details: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    """评估报告."""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    intent_accuracy: float = 0.0
    injection_block_rate: float = 0.0
    param_fidelity: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    results: list[CaseResult] = Field(default_factory=list)
    duration_ms: float = 0.0


class EvalRunner:
    """自动化评估运行器."""

    def __init__(self, dataset_path: Optional[str] = None):
        if dataset_path is None:
            project_root = Path(__file__).parent.parent.parent
            dataset_path = str(project_root / "tests" / "eval" / "qa_dataset.json")
        self._dataset_path = dataset_path
        self._dataset: list[dict] | None = None

    def load_dataset(self) -> list[dict]:
        """加载 QA 数据集."""
        if self._dataset is None:
            path = Path(self._dataset_path)
            if not path.exists():
                logger.warning(f"[EvalRunner] Dataset not found: {path}")
                self._dataset = []
                return []
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # 同时支持 list 和 {"cases": [...]} 两种格式
            if isinstance(raw, list):
                self._dataset = raw
            elif isinstance(raw, dict) and "cases" in raw:
                self._dataset = raw["cases"]
            else:
                self._dataset = []
        return self._dataset

    def run_single(self, case: dict) -> CaseResult:
        """执行单个用例评估（零 LLM 确定性模式）."""
        case_id = case.get("id", "unknown")
        user_input = case.get("input", case.get("user_input", ""))
        expected_skill = case.get("v8_mode_skill", case.get("expected_intent", ""))
        expected_params = case.get("expected_params", {})
        case_type = case.get("category", case.get("type", "normal"))

        start = time.perf_counter()
        result = CaseResult(case_id=case_id, case_type=case_type)

        try:
            # 1. 意图分类（确定性模式 — 同步调用 _rule_match）
            from src.v8.lead_router import LeadRouter

            router = LeadRouter()
            # 使用同步规则匹配以实现零 LLM 评估
            plan = router._rule_match(user_input, expected_params)

            if plan is None:
                result.intent_correct = False
                result.details.append("No skill matched (rule match returned None)")
            else:
                result.intent_correct = plan.scenario_id == expected_skill
                if not result.intent_correct:
                    result.details.append(f"Skill mismatch: expected={expected_skill}, " f"got={plan.scenario_id}")

            # 2. 注入检测
            from src.v8.security import run_security_check

            security = run_security_check(user_input)
            if case_type in ("injection", "attack"):
                result.injection_blocked = not security.passed
                if not result.injection_blocked:
                    result.details.append("Injection NOT blocked!")
            else:
                result.injection_blocked = security.passed

            # 3. 参数保真度
            if expected_params:
                params_ok = True
                actual_params = plan.normalized_params
                for key, expected_val in expected_params.items():
                    actual_val = actual_params.get(key)
                    if actual_val != expected_val:
                        params_ok = False
                        result.details.append(f"Param '{key}' mismatch: " f"expected={expected_val}, got={actual_val}")
                result.params_match = params_ok

            result.passed = (
                result.intent_correct and (result.injection_blocked is not False) and (result.params_match is not False)
            )

        except Exception as e:
            result.details.append(f"Error: {e}")
            result.passed = False

        result.latency_ms = (time.perf_counter() - start) * 1000
        return result

    async def run_suite(self) -> EvalReport:
        """执行完整评估套件."""

        start = time.perf_counter()
        dataset = self._dataset if self._dataset is not None else self.load_dataset()

        if not dataset:
            return EvalReport(total_cases=0, passed=0, failed=0, duration_ms=(time.perf_counter() - start) * 1000)

        results: list[CaseResult] = []
        for case in dataset:
            result = self.run_single(case)
            results.append(result)

        # 计算指标
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        intents_correct = sum(1 for r in results if r.intent_correct)

        injection_cases = [r for r in results if r.case_type == "injection"]
        injection_blocked = sum(1 for r in injection_cases if r.injection_blocked)

        param_cases = [r for r in results if r.params_match is not None]
        params_correct = sum(1 for r in param_cases if r.params_match)

        latencies = sorted(r.latency_ms for r in results)
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[min(p95_idx, len(latencies) - 1)] if latencies else 0

        return EvalReport(
            total_cases=total,
            passed=passed,
            failed=total - passed,
            intent_accuracy=intents_correct / total if total > 0 else 0.0,
            injection_block_rate=(injection_blocked / len(injection_cases) if injection_cases else 1.0),
            param_fidelity=(params_correct / len(param_cases) if param_cases else 1.0),
            latency_p50=p50,
            latency_p95=p95,
            results=results,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    def compare_with_baseline(self, current: EvalReport, baseline: EvalReport) -> dict:
        """对比当前结果与基线."""
        return {
            "total_cases": current.total_cases,
            "current_intent_accuracy": current.intent_accuracy,
            "baseline_intent_accuracy": baseline.intent_accuracy,
            "intent_delta": current.intent_accuracy - baseline.intent_accuracy,
            "current_latency_p50": current.latency_p50,
            "baseline_latency_p50": baseline.latency_p50,
            "latency_delta_ms": current.latency_p50 - baseline.latency_p50,
            "degradation": current.intent_accuracy < baseline.intent_accuracy,
        }

    def format_report(self, report: EvalReport) -> str:
        """格式化报告为 Markdown."""
        lines = [
            "# Agent 评估报告",
            "",
            "## 概要",
            f"- 总用例: {report.total_cases}",
            f"- 通过: {report.passed}",
            f"- 失败: {report.failed}",
            f"- 耗时: {report.duration_ms:.1f}ms",
            "",
            "## 指标",
            "| 指标 | 值 | 目标 |",
            "|------|-----|------|",
            f"| 意图准确率 | {report.intent_accuracy:.1%} | ≥ 95% |",
            f"| 注入拦截率 | {report.injection_block_rate:.1%} | 100% |",
            f"| 参数保真度 | {report.param_fidelity:.1%} | ≥ 90% |",
            f"| P50 延迟 | {report.latency_p50:.1f}ms | < 2s |",
            f"| P95 延迟 | {report.latency_p95:.1f}ms | < 5s |",
            "",
        ]
        failed = [r for r in report.results if not r.passed]
        if failed:
            lines.append("## 失败用例")
            for r in failed:
                lines.append(f"- **{r.case_id}**: {'; '.join(r.details)}")
        return "\n".join(lines)
