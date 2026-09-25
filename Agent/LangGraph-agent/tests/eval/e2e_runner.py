"""
端到端评估运行器（E2ERunner）—— 真实调用主图的全链路评估。

【与 tests/eval/runner.py 的分工】
- runner.py: 规则层快速评估（零 LLM，日常门禁）
- e2e_runner.py: 端到端评估（真实 LLM + 真实图执行，里程碑/提交前运行）

【评估分层】（书籍 Ch6）
1. 确定性检查先行（checks.py）—— 意图/参数/工具/数字幻觉/路径
2. 幻觉 veto —— 数字溯源失败直接判 fail，不进入 Rubric
3. Rubric LLM 评判（rubric_judge.py，可选）—— 仅对确定性全过的用例

【使用】
    python scripts/run_eval.py --e2e
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .checks import first_failure, run_all_checks
from .failure_diagnosis import (
    aggregate_first_failures,
    pass_at_k,
)

logger = logging.getLogger(__name__)

# 单用例超时（秒）：本地 14b 冷启动 + 多轮循环的保守上限
CASE_TIMEOUT_S = 180


class E2ECaseResult(BaseModel):
    """单条端到端用例结果."""

    case_id: str
    category: str = "normal"
    passed: bool = False
    checks: list[dict] = Field(default_factory=list)
    first_error: Optional[str] = None  # 失败归因：首个错误检查项
    processing_path: str = ""
    intent: Optional[str] = None
    rubric_scores: Optional[dict] = None  # Rubric 评判结果（可选）
    latency_ms: float = 0.0
    error: Optional[str] = None  # 执行级错误（超时/崩溃）


class E2EReport(BaseModel):
    """端到端评估报告."""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    intent_accuracy: float = 0.0  # 有预期意图的用例
    injection_block_rate: float = 0.0
    hallucination_vetoes: int = 0  # 数字幻觉 veto 次数（目标 = 0）
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    results: list[E2ECaseResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    # 错误归因聚合（书籍 Ch6）：按"首个错误检查项"统计
    failure_attribution: dict = Field(default_factory=dict)
    # Pass@k（可选，run_suite_passk 填充）
    passk: Optional[dict] = None  # {"k": 3, "samples": 5, "pass_at_k": 0.83, "per_case": {...}}


class E2ERunner:
    """端到端评估运行器（真实图执行）."""

    def __init__(self, dataset_path: Optional[str] = None):
        if dataset_path is None:
            project_root = Path(__file__).parent.parent.parent
            dataset_path = str(project_root / "tests" / "eval" / "e2e_dataset.json")
        self._dataset_path = dataset_path
        self._judge: Any = None  # 可选 Rubric 评判器（run_suite 时注入）

    def load_dataset(self) -> list[dict]:
        """加载 e2e 数据集."""
        path = Path(self._dataset_path)
        if not path.exists():
            logger.warning(f"[E2ERunner] Dataset not found: {path}")
            return []
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict) and "cases" in raw:
            return raw["cases"]
        return []

    async def run_case(self, case: dict) -> E2ECaseResult:
        """执行单条用例：真实调用主图 → 确定性检查 → 归因."""
        from src.graph.main_graph import get_graph
        from src.graph.state import create_initial_state

        case_id = case.get("id", "unknown")
        result = E2ECaseResult(case_id=case_id, category=case.get("category", "normal"))
        start = time.perf_counter()

        try:
            graph = get_graph()
            thread_id = f"eval-{uuid.uuid4().hex[:10]}"
            state = create_initial_state(case["input"], thread_id)
            config = {"configurable": {"thread_id": thread_id}}

            final_state = await asyncio.wait_for(graph.ainvoke(state, config), timeout=CASE_TIMEOUT_S)
        except asyncio.TimeoutError:
            result.error = f"timeout > {CASE_TIMEOUT_S}s"
            result.first_error = "execution_timeout"
            result.latency_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:  # noqa: BLE001 - 评估器不能因单用例崩溃
            result.error = str(e)
            result.first_error = "execution_error"
            result.latency_ms = (time.perf_counter() - start) * 1000
            return result

        # 确定性检查（先行于任何 LLM 评判）
        checks = run_all_checks(case, final_state)
        result.checks = checks
        result.processing_path = final_state.get("processing_path", "")
        result.intent = final_state.get("intent")

        failure = first_failure(checks)
        if failure:
            result.first_error = f"{failure['check']}: {failure['evidence']}"
        result.passed = failure is None

        # Rubric 评判：仅对确定性检查全过的用例（LLM 评判其后）
        if result.passed and self._judge is not None:
            result.rubric_scores = await self._judge.judge(case, final_state)

        result.latency_ms = (time.perf_counter() - start) * 1000
        return result

    async def run_suite(self, judge: Any = None) -> E2EReport:
        """顺序执行全部用例（避免并发压垮本地推理）.

        【参数】judge: 可选 Rubric 评判器（需有 async judge(case, state) 方法）
        """
        self._judge = judge
        start = time.perf_counter()
        dataset = self.load_dataset()
        if not dataset:
            return E2EReport(duration_ms=(time.perf_counter() - start) * 1000)

        results: list[E2ECaseResult] = []
        for i, case in enumerate(dataset, 1):
            # print 而非 logger：长时间运行需逐用例可见进度（日志级别默认 WARNING）
            print(f"[E2E] ({i}/{len(dataset)}) {case.get('id')} ...", flush=True)
            result = await self.run_case(case)
            results.append(result)
            mark = "PASS" if result.passed else "FAIL"
            reason = "" if result.passed else f" <- {result.first_error or result.error or ''}"
            print(
                f"[E2E] ({i}/{len(dataset)}) {case.get('id')} {mark} " f"({result.latency_ms / 1000:.1f}s){reason}",
                flush=True,
            )

        total = len(results)
        passed = sum(1 for r in results if r.passed)

        # 意图准确率：仅统计有预期意图的用例（evidence 不含“跳过”）
        intent_checked = [
            c for r in results for c in r.checks if c["check"] == "intent" and "跳过" not in c.get("evidence", "")
        ]
        intent_correct = sum(1 for c in intent_checked if c["passed"])

        inj_cases = [r for r in results if r.category == "injection"]
        inj_blocked = sum(1 for r in inj_cases if r.passed)

        hallucination_vetoes = sum(
            1 for r in results if any(c["check"] == "numbers" and not c["passed"] for c in r.checks)
        )

        latencies = sorted(r.latency_ms for r in results)
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)] if latencies else 0

        return E2EReport(
            total_cases=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total if total else 0.0,
            intent_accuracy=intent_correct / len(intent_checked) if intent_checked else 0.0,
            injection_block_rate=inj_blocked / len(inj_cases) if inj_cases else 1.0,
            hallucination_vetoes=hallucination_vetoes,
            latency_p50=p50,
            latency_p95=p95,
            results=results,
            duration_ms=(time.perf_counter() - start) * 1000,
            failure_attribution=aggregate_first_failures(results),
        )

    async def run_suite_passk(self, judge: Any = None, samples: int = 3, k: int = 3) -> E2EReport:
        """Pass@k 采样评估：关键用例固定 seed 多采样，输出 pass@k。

        【书籍 Ch6】只跑一次取 pass_rate 存在单次抽样噪声；
        对每个用例采样 samples 次，用无偏估计器求 pass@k
        （k 次尝试内至少一次通过的成功率）。

        【注意】真实 LLM 推理下"固定 seed"仅表示对同用例重复执行
        （复用同 thread_id 前缀保证可复现），采样间仍存在模型随机性。
        """
        self._judge = judge
        start = time.perf_counter()
        dataset = self.load_dataset()
        if not dataset:
            return E2EReport(duration_ms=(time.perf_counter() - start) * 1000)

        # 每个用例采样 samples 次，统计通过次数 c，求 pass@k
        pass_counts: dict[str, int] = {}
        per_case_passk: dict[str, float] = {}
        all_results: list[E2ECaseResult] = []
        for i, case in enumerate(dataset, 1):
            case_id = case.get("id", f"case-{i}")
            passed_this_case = 0
            for s in range(samples):
                print(
                    f"[PASSK] ({i}/{len(dataset)}) {case_id} sample {s + 1}/{samples} ...",
                    flush=True,
                )
                res = await self.run_case(case)
                all_results.append(res)
                if res.passed:
                    passed_this_case += 1
            pass_counts[case_id] = passed_this_case
            per_case_passk[case_id] = pass_at_k(samples, passed_this_case, k)
            print(
                f"[PASSK] ({i}/{len(dataset)}) {case_id} "
                f"c={passed_this_case}/{samples} pass@k={per_case_passk[case_id]:.2f}",
                flush=True,
            )

        # 聚合 pass@k（各用例的算术平均）
        avg_passk = sum(per_case_passk.values()) / len(per_case_passk) if per_case_passk else 0.0
        total = len(dataset)
        passed = sum(1 for r in all_results if r.passed)
        latencies = sorted(r.latency_ms for r in all_results)

        return E2EReport(
            total_cases=total,
            passed=passed,
            failed=(samples * total) - passed,
            pass_rate=passed / (samples * total) if samples * total else 0.0,
            latency_p50=latencies[len(latencies) // 2] if latencies else 0.0,
            latency_p95=(latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)] if latencies else 0.0),
            results=all_results,
            duration_ms=(time.perf_counter() - start) * 1000,
            failure_attribution=aggregate_first_failures(all_results),
            passk={
                "k": k,
                "samples": samples,
                "pass_at_k": round(avg_passk, 4),
                "per_case": per_case_passk,
                "pass_counts": pass_counts,
            },
        )

    def format_report(self, report: E2EReport) -> str:
        """格式化为 Markdown."""
        lines = [
            "# Agent 端到端评估报告",
            "",
            "## 概要",
            f"- 总用例: {report.total_cases}（通过 {report.passed} / 失败 {report.failed}）",
            f"- 总耗时: {report.duration_ms / 1000:.1f}s",
            "",
            "## 指标",
            "| 指标 | 值 | 目标 |",
            "|------|-----|------|",
            f"| 端到端通过率 | {report.pass_rate:.1%} | ≥ 基线 |",
            f"| 意图准确率 | {report.intent_accuracy:.1%} | ≥ 95% |",
            f"| 注入拦截率 | {report.injection_block_rate:.1%} | 100% |",
            f"| 幻觉 veto | {report.hallucination_vetoes} | 0 |",
            f"| P50 延迟 | {report.latency_p50:.0f}ms | - |",
            f"| P95 延迟 | {report.latency_p95:.0f}ms | - |",
            "",
        ]
        failed = [r for r in report.results if not r.passed]
        if failed:
            lines.append("## 失败归因（首个错误）")
            for r in failed:
                err = r.error or r.first_error or "unknown"
                lines.append(f"- **{r.case_id}** ({r.category}): {err}")

        # 错误归因聚合（书籍 Ch6：哪里先错）
        agg = report.failure_attribution or {}
        if agg.get("total_failed"):
            lines.append("")
            lines.append("## 错误归因聚合（按首错检查项）")
            lines.append("| 首错检查项 | 次数 | 占比 |")
            lines.append("|---|---|---|")
            for item in agg.get("top", []):
                lines.append(f"| {item['check']} | {item['count']} | {item['ratio']:.1%} |")

        # Pass@k
        if report.passk:
            p = report.passk
            lines.append("")
            lines.append(f"## Pass@{p['k']}（每用例采样 {p['samples']} 次）")
            lines.append(f"- 聚合 pass@{p['k']}: {p['pass_at_k']:.1%}")
            worst = sorted(p.get("per_case", {}).items(), key=lambda kv: kv[1])[:5]
            if worst:
                lines.append("- 最薄弱用例（pass@k 最低 5 个）:")
                for cid, v in worst:
                    lines.append(f"  - {cid}: pass@k={v:.0%}")

        return "\n".join(lines)
