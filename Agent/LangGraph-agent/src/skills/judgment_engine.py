"""声明式判断引擎 — 通用阈值评估。

从 Skill YAML 的 judgment 字段注册规则，
对 data_summary 逐条匹配，返回结构化判断。
Fast Path 和 Normal Path 共用同一引擎。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from .schema import JudgmentCondition, JudgmentDefault

logger = logging.getLogger(__name__)

# 状态优先级（用于多规则结果合并）
_STATUS_PRIORITY = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


@dataclass
class JudgmentRule:
    """一条判断规则（从 Skill YAML 解析）。"""

    metric: str
    extract_pattern: re.Pattern
    conditions: list[JudgmentCondition]
    default: JudgmentDefault
    actions: dict[str, list[str]]


class JudgmentEngine:
    """通用声明式判断引擎。

    使用方式：
        engine = JudgmentEngine()
        engine.register_rule(metric="spanloss", ...)
        result = engine.evaluate("spanloss=9.5")
        # result = {"status": "CRITICAL", "findings": [...], "metrics": {...}, "actions": [...]}
    """

    def __init__(self):
        self._rules: list[JudgmentRule] = []

    def register_rule(
        self,
        metric: str,
        extract_pattern: str,
        conditions: list[JudgmentCondition],
        default: JudgmentDefault,
        actions: dict[str, list[str]],
    ) -> None:
        """注册一条判断规则。"""
        self._rules.append(
            JudgmentRule(
                metric=metric,
                extract_pattern=re.compile(extract_pattern, re.IGNORECASE),
                conditions=conditions,
                default=default,
                actions=actions,
            )
        )

    def clear(self) -> None:
        """清空所有规则（热加载前调用）。"""
        self._rules.clear()

    def evaluate(self, data_summary: str) -> dict[str, Any]:
        """对 data_summary 逐条规则匹配，返回结构化判断。

        Returns:
            {
                "status": "CRITICAL" | "WARNING" | "NORMAL",
                "findings": ["衰耗 9.5dB 严重超标", ...],
                "metrics": {"spanloss": 9.5, ...},
                "actions": ["立即派单检修", ...],
            }
        """
        findings: list[str] = []
        metrics: dict[str, float] = {}
        status = "NORMAL"
        all_actions: list[str] = []

        for rule in self._rules:
            value = self._extract(rule, data_summary)
            if value is None:
                continue

            metrics[rule.metric] = value
            result = self._evaluate_conditions(rule, value)
            findings.append(result["finding"])

            if _STATUS_PRIORITY.get(result["status"], 0) > _STATUS_PRIORITY.get(status, 0):
                status = result["status"]
                all_actions = rule.actions.get(status, [])

        return {
            "status": status,
            "findings": findings,
            "metrics": metrics,
            "actions": all_actions,
        }

    def _extract(self, rule: JudgmentRule, data: str) -> Optional[float]:
        """从 data_summary 中提取指标值。"""
        m = rule.extract_pattern.search(data)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                return None
        return None

    def _evaluate_conditions(self, rule: JudgmentRule, value: float) -> dict[str, str]:
        """按优先级评估条件列表。"""
        for cond in rule.conditions:
            threshold = self._resolve_value(cond.value)
            if self._compare(value, cond.op, threshold):
                finding = cond.finding.format(
                    value=value,
                    percent=round((value - threshold) / threshold * 100) if threshold else 0,
                )
                return {"status": cond.status, "finding": finding}

        # 所有条件不满足 → 默认
        finding = rule.default.finding.format(value=value)
        return {"status": rule.default.status, "finding": finding}

    def _compare(self, value: float, op: str, threshold: float) -> bool:
        """执行比较操作。"""
        if op == ">":
            return value > threshold
        elif op == "<":
            return value < threshold
        elif op == "==":
            return value == threshold
        elif op == "count_gt":
            return value > threshold
        elif op == "not_in_range":
            # threshold 在此场景下作为上界（简化处理）
            return value > threshold
        return False

    def _resolve_value(self, raw: str) -> float:
        """解析条件值：${VAR} → config 环境变量，字面量 → 直接转换。"""
        if raw.startswith("${") and raw.endswith("}"):
            var_name = raw[2:-1]
            try:
                from .. import config

                return float(getattr(config, var_name, 0))
            except (ImportError, AttributeError, TypeError):
                return 0.0
        try:
            return float(raw)
        except ValueError:
            return 0.0
