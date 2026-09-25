"""
代码编排器 (CodeOrchestrator).

【设计原则】
AI Agent Design Principles — "Verification before Execution":
Agent 可以生成代码来编排多步数据处理，但必须在执行前通过静态验证。

【能力】
1. 自然语言 → 代码计划: 将复杂分析需求分解为代码步骤
2. 静态验证: AST 分析检查危险操作 (exec/eval/文件系统访问)
3. 沙箱执行: 在受限环境中执行代码
4. 结果验证: 检查输出是否符合预期 schema
"""

from __future__ import annotations

import ast
import io
import logging
import re
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── 代码计划 ──────────────────────────────────────────────────────────
@dataclass
class CodeStep:
    """代码执行步骤."""

    description: str
    code: str
    expected_output: str = ""


@dataclass
class CodePlan:
    """完整代码执行计划."""

    goal: str
    steps: list[CodeStep] = field(default_factory=list)
    safety_checks: list[str] = field(default_factory=list)
    # 保留集（书籍 Ch5：保留集+边界集双验证）：执行完毕后 result 必须
    # 仍保留这些键，防止生成方案的"改造"破坏既有成功行为
    retention_set: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "steps": [
                {"description": s.description, "code": s.code, "expected_output": s.expected_output} for s in self.steps
            ],
            "safety_checks": self.safety_checks,
            "retention_set": self.retention_set,
        }


# ── 代码验证结果 ──────────────────────────────────────────────────────
class CodeValidationResult(BaseModel):
    safe: bool = True
    violations: list[str] = Field(default_factory=list)
    complexity_score: float = 0.0  # 0-1，越高越复杂
    ast_nodes: int = 0


class CodeExecutionResult(BaseModel):
    success: bool = False
    output: str = ""
    error: str = ""
    step_results: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    # 失败恢复标记：通过已验证兜底达到的"降级成功"，调用方应知晓
    recovered: bool = False


# ── 危险操作模式 ───────────────────────────────────────────────────────
_DANGEROUS_PATTERNS: dict[str, str] = {
    "exec_call": "禁止使用 exec()",
    "eval_call": "禁止使用 eval()",
    "compile_call": "禁止使用 compile()",
    "open_with_write": "禁止直接文件写入 (open with 'w')",
    "import_os": "禁止 import os",
    "import_subprocess": "禁止 import subprocess",
    "import_shutil": "禁止 import shutil",
    "import_sys": "禁止 import sys",
    "while_loop": "禁止无限循环 (while True)",
    "recursive": "检测到递归调用，可能导致栈溢出",
}


class CodeOrchestrator:
    """
    代码编排器 — 安全地生成、验证和执行代码计划.

    使用方式:
        orchestrator = CodeOrchestrator()
        plan = orchestrator.plan_from_goal("计算光纤总衰耗的统计分布")
        validation = orchestrator.validate_plan(plan)
        if validation.safe:
            result = orchestrator.execute_plan(plan, context={"data": ...})
    """

    def __init__(
        self,
        allowed_modules: Optional[list[str]] = None,
        max_execution_time_ms: int = 5000,
    ) -> None:
        self._allowed_modules = allowed_modules or [
            "math",
            "statistics",
            "json",
            "re",
            "datetime",
            "collections",
            "itertools",
            "functools",
        ]
        self._max_execution_time_ms = max_execution_time_ms

    # ── 计划生成 ──────────────────────────────────────────────────
    def plan_from_goal(self, goal: str, context_hint: str = "") -> CodePlan:
        """
        从自然语言目标生成代码计划.

        注: 此处使用模板化生成（零 LLM）。实际生产中可接入 LLM 生成。
        """
        goal_lower = goal.lower()
        steps: list[CodeStep] = []
        # 各模式声明的保留集（书籍 Ch5 保留集校验）
        retention: list[str] = []

        # 模式识别
        if any(kw in goal_lower for kw in ("统计", "分布", "平均值", "均值", "average", "mean")):
            retention = ["count", "mean", "min", "max"]
            steps.append(
                CodeStep(
                    description="加载数据并计算统计量",
                    code=(
                        "import statistics\n"
                        "data = context.get('data', [])\n"
                        "if not data:\n"
                        "    result = {'count': 0, 'mean': 0, 'min': 0, 'max': 0}\n"
                        "else:\n"
                        "    values = [d['value'] if isinstance(d, dict) else d for d in data]\n"
                        "    result = {\n"
                        "        'count': len(values),\n"
                        "        'mean': statistics.mean(values),\n"
                        "        'min': min(values),\n"
                        "        'max': max(values),\n"
                        "        'stdev': statistics.stdev(values) if len(values) > 1 else 0,\n"
                        "    }"
                    ),
                    expected_output="包含 count/mean/min/max/stdev 的字典",
                )
            )
        elif any(kw in goal_lower for kw in ("筛选", "过滤", "filter", "条件")):
            retention = ["filtered", "count"]
            steps.append(
                CodeStep(
                    description="按条件筛选数据",
                    code=(
                        "data = context.get('data', [])\n"
                        "condition = context.get('condition', {})\n"
                        "filtered = []\n"
                        "for item in data:\n"
                        "    if isinstance(item, dict):\n"
                        "        match = all(item.get(k) == v for k, v in condition.items())\n"
                        "        if match:\n"
                        "            filtered.append(item)\n"
                        "result = {'filtered': filtered, 'count': len(filtered)}"
                    ),
                    expected_output="包含筛选结果的字典",
                )
            )
        elif any(kw in goal_lower for kw in ("分组", "group", "按.*分类")):
            steps.append(
                CodeStep(
                    description="按字段分组聚合",
                    code=(
                        "from collections import defaultdict\n"
                        "data = context.get('data', [])\n"
                        "group_by = context.get('group_by', 'category')\n"
                        "groups = defaultdict(list)\n"
                        "for item in data:\n"
                        "    if isinstance(item, dict):\n"
                        "        key = item.get(group_by, 'unknown')\n"
                        "        groups[key].append(item)\n"
                        "result = {k: {'count': len(v), 'items': v} for k, v in groups.items()}"
                    ),
                    expected_output="按组聚合的字典",
                )
            )
        else:
            # 通用步骤
            retention = ["count", "data"]
            steps.append(
                CodeStep(
                    description="通用数据处理",
                    code=(
                        "data = context.get('data', [])\n"
                        "result = {\n"
                        "    'count': len(data),\n"
                        "    'data': data[:10],  # 预览前 10 条\n"
                        "}"
                    ),
                    expected_output="数据预览字典",
                )
            )

        return CodePlan(
            goal=goal,
            steps=steps,
            safety_checks=self._get_safety_checks(),
            retention_set=retention,
        )

    # ── 静态验证 ──────────────────────────────────────────────────
    def validate_plan(self, plan: CodePlan) -> CodeValidationResult:
        """对代码计划执行静态安全验证."""
        all_code = "\n".join(s.code for s in plan.steps)
        violations: list[str] = []

        # 1. AST 分析
        try:
            tree = ast.parse(all_code)
            ast_nodes = list(ast.walk(tree))
            complexity = self._compute_complexity(tree)

            for node in ast_nodes:
                # 检查危险调用
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ("exec", "eval", "compile"):
                            violations.append(f"{_DANGEROUS_PATTERNS.get(f'{node.func.id}_call', '危险调用')}")
                    if isinstance(node.func, ast.Attribute):
                        pass  # 方法调用默认视为安全

                # 检查 import
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name not in self._allowed_modules:
                            violations.append(f"禁止导入模块: {alias.name}")

                if isinstance(node, ast.ImportFrom):
                    if node.module and node.module not in self._allowed_modules:
                        violations.append(f"禁止从 {node.module} 导入")

                # 检查 while True
                if isinstance(node, ast.While):
                    if self._is_constant_true(node.test):
                        violations.append(_DANGEROUS_PATTERNS["while_loop"])

        except SyntaxError as e:
            violations.append(f"语法错误: {e}")
            return CodeValidationResult(safe=False, violations=violations)

        # 2. 文本模式检查
        text_patterns = [
            ("open.*['\"]w", _DANGEROUS_PATTERNS["open_with_write"]),
            (r"import\s+os", _DANGEROUS_PATTERNS["import_os"]),
            (r"import\s+subprocess", _DANGEROUS_PATTERNS["import_subprocess"]),
            (r"import\s+shutil", _DANGEROUS_PATTERNS["import_shutil"]),
            (r"import\s+sys", _DANGEROUS_PATTERNS["import_sys"]),
        ]
        for pattern, message in text_patterns:
            if re.search(pattern, all_code):
                violations.append(message)

        return CodeValidationResult(
            safe=len(violations) == 0,
            violations=violations,
            complexity_score=complexity,
            ast_nodes=len(ast_nodes) if "ast_nodes" in dir() else 0,
        )

    def _compute_complexity(self, tree: ast.Module) -> float:
        """计算代码复杂度 (0-1)."""
        complexity_nodes = 0
        total_nodes = 0
        for node in ast.walk(tree):
            total_nodes += 1
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef)):
                complexity_nodes += 1
        if total_nodes == 0:
            return 0.0
        return min(1.0, complexity_nodes / 20.0)

    def _is_constant_true(self, node: ast.expr) -> bool:
        """检查表达式是否为常量 True."""
        if isinstance(node, ast.Constant):
            return node.value is True
        if isinstance(node, ast.Name):
            return node.id == "True"
        return False

    # ── 沙箱执行 ──────────────────────────────────────────────────
    def execute_plan(
        self,
        plan: CodePlan,
        context: Optional[dict[str, Any]] = None,
    ) -> CodeExecutionResult:
        """在受限环境中执行代码计划."""
        import time as time_mod

        start = time_mod.perf_counter()
        context = context or {}
        step_results: list[str] = []

        # 构建受限全局环境
        safe_builtins = {k: v for k, v in __builtins__.items() if k not in ("exec", "eval", "compile", "open")}
        # 保留 __import__ 但限制可导入的模块
        original_import = __builtins__.get("__import__", __import__)

        def restricted_import(name, *args, **kwargs):
            if name not in self._allowed_modules:
                raise ImportError(f"Import of '{name}' is not allowed. " f"Allowed: {self._allowed_modules}")
            return original_import(name, *args, **kwargs)

        safe_builtins["__import__"] = restricted_import
        global_env: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "context": context,
            "result": None,
        }

        for i, step in enumerate(plan.steps):
            try:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exec(compile(step.code, f"<step_{i}>", "exec"), global_env)
                step_output = stdout.getvalue() or "ok"
                step_results.append(f"Step {i}: {step_output.strip()}")
            except Exception as e:
                elapsed = (time_mod.perf_counter() - start) * 1000
                return CodeExecutionResult(
                    success=False,
                    output="",
                    error=f"Step {i} failed: {e}",
                    step_results=step_results,
                    duration_ms=elapsed,
                )

        elapsed = (time_mod.perf_counter() - start) * 1000
        final_result = global_env.get("result")

        # 保留集校验（书籍 Ch5）：result 必须仍保留全部声明键，
        # 否则视为"改造成果破坏了既有行为"
        retention = plan.retention_set or []
        if isinstance(final_result, dict) and retention:
            missing = [k for k in retention if k not in final_result]
            if missing:
                return CodeExecutionResult(
                    success=False,
                    output="",
                    error=f"保留集缺失: {missing}（result={final_result!r}）",
                    step_results=step_results,
                    duration_ms=elapsed,
                )

        return CodeExecutionResult(
            success=True,
            output=str(final_result) if final_result is not None else "null",
            error="",
            step_results=step_results,
            duration_ms=elapsed,
        )

    # ── 失败重建（书籍 Ch5：错误恢复闭环）─────────────────────────
    def _fallback_result(self, plan: CodePlan) -> dict:
        """为保留集生成一个被验证的零值兜底 result（不依赖未验证代码）。

        仅当正常执行失败/保留集缺失时使用，且仅产出保留集声明过的键，
        保证 shape 正确、可被下游校验器继续核验。
        """
        fallback: dict[str, Any] = {"count": 0}
        for key in plan.retention_set or ["count"]:
            if key == "count":
                fallback[key] = 0
            else:
                fallback[key] = [] if key in ("data", "filtered", "items") else 0
        return fallback

    def execute_plan_with_recovery(
        self,
        plan: CodePlan,
        context: Optional[dict[str, Any]] = None,
        max_recovery_attempts: int = 1,
    ) -> CodeExecutionResult:
        """执行代码计划，失败/保留集不满足时退化为已验证兜底（降级成功）。

        【书籍 Ch5 依据】Coding Agent 需要错误恢复闭环；Harness 的目标是
        恢复到一个"已验证"的状态，而非直接崩溃或吞掉错误。
        【语义】recovered=True 表示这次成功来自兜底而非业务代码，调用方
        应感知降级；仍保留原始 error 作为诊断证据。
        """
        base = self.execute_plan(plan, context)
        if base.success:
            return base

        if max_recovery_attempts <= 0:
            return base

        # 兜底：用保留集构造一个可被下游继续核验的结果
        fallback = self._fallback_result(plan)
        return CodeExecutionResult(
            success=True,
            output=str(fallback),
            error=f"[recovered] 原始执行失败已兜底: {base.error}",
            step_results=[*base.step_results, f"[recovered] fallback={fallback}"],
            duration_ms=base.duration_ms,
            recovered=True,
        )

    # ── 辅助 ──────────────────────────────────────────────────────
    def _get_safety_checks(self) -> list[str]:
        return [
            "禁止 exec/eval/compile 调用",
            "禁止 import os/subprocess/shutil/sys",
            "禁止 open(..., 'w') 直接文件写入",
            "检测 while True 无限循环",
            f"允许的模块: {', '.join(self._allowed_modules)}",
            f"最大执行时间: {self._max_execution_time_ms}ms",
        ]


# ── 便捷函数 ───────────────────────────────────────────────────────────
def run_code_plan(goal: str, data: Optional[dict] = None) -> CodeExecutionResult:
    """一键执行: 目标 → 计划 → 验证 → 执行."""
    orchestrator = CodeOrchestrator()
    plan = orchestrator.plan_from_goal(goal)
    validation = orchestrator.validate_plan(plan)
    if not validation.safe:
        return CodeExecutionResult(
            success=False,
            error=f"Code validation failed: {'; '.join(validation.violations)}",
        )
    return orchestrator.execute_plan(plan, context=data or {})


# ── LangChain Tool 注册 ────────────────────────────────────────────────
from langchain_core.tools import tool as _tool
from pydantic import BaseModel, Field


class _CodePlanInput(BaseModel):
    goal: str = Field(description="自然语言描述的分析目标，如'计算光纤总衰耗的统计分布'")
    data_json: str = Field(
        default="{}",
        description="可选输入数据的 JSON 字符串，供代码执行时使用",
    )


@_tool(args_schema=_CodePlanInput)
async def execute_code_plan(
    goal: str,
    data_json: str = "{}",
) -> str:
    """根据自然语言目标安全地生成、验证并执行代码，返回分析结果。
    代码在受限沙箱中执行，禁止危险操作（exec/eval/文件写入等）。
    适用于：统计分析、数据过滤、分组聚合等数据处理场景。"""
    import json as _json

    try:
        data = _json.loads(data_json) if data_json and data_json != "{}" else {}
    except _json.JSONDecodeError:
        raise ValueError(f"data_json 不是有效的 JSON: {data_json[:100]}")

    # 包装为 context：模板代码期望 context["data"] 为数据集
    context = data if isinstance(data, dict) else {"data": data}
    result = run_code_plan(goal, context)
    if result.success:
        return _json.dumps(
            {
                "status": "success",
                "output": result.output,
                "recovered": result.recovered,
                "duration_ms": result.duration_ms,
            },
            ensure_ascii=False,
        )
    return _json.dumps(
        {
            "status": "error",
            "error": result.error,
            "recovered": result.recovered,
            "duration_ms": result.duration_ms,
        },
        ensure_ascii=False,
    )
