"""
记忆评估框架 (MemoryEvalFramework).

【设计原则】
AI Agent Design Principles — "记忆不是越多越好，
而是越相关、越准确、越有时效性越好".

【评估维度】
1. 相关性 (Relevance): 记忆内容与当前任务的关联程度
2. 准确性 (Accuracy): 记忆内容与事实/历史的一致程度
3. 时效性 (Freshness): 记忆的新旧程度
4. 覆盖度 (Coverage): 记忆是否覆盖了关键信息领域
5. 冗余度 (Redundancy): 是否存在重复或冲突的记忆
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── 记忆条目 ──────────────────────────────────────────────────────────
@dataclass
class MemoryEntry:
    """单个记忆条目."""

    id: str
    content: str
    category: str  # "preference", "history", "fact", "pattern"
    created_at: float = 0.0
    updated_at: float = 0.0
    access_count: int = 0
    last_accessed_at: float = 0.0
    confidence: float = 1.0  # 0-1, 置信度
    source: str = "user"  # "user", "system", "agent"
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 评估结果 ──────────────────────────────────────────────────────────
class MemoryEvalScore(BaseModel):
    """单个维度的评估分数."""

    dimension: str  # "relevance", "accuracy", "freshness", "coverage", "redundancy"
    score: float = 0.0  # 0-1
    details: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class MemoryEvalReport(BaseModel):
    """完整记忆评估报告."""

    overall_score: float = 0.0
    scores: list[MemoryEvalScore] = Field(default_factory=list)
    entry_count: int = 0
    category_distribution: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    generated_at: float = 0.0


# ── 记忆评估框架 ──────────────────────────────────────────────────────
class MemoryEvalFramework:
    """
    记忆评估框架.

    使用方式:
        evaluator = MemoryEvalFramework()
        entries = [...]  # MemoryEntry 列表
        report = evaluator.evaluate(entries, context="查询光纤性能")
    """

    def __init__(
        self,
        relevance_weight: float = 0.3,
        accuracy_weight: float = 0.25,
        freshness_weight: float = 0.2,
        coverage_weight: float = 0.15,
        redundancy_weight: float = 0.1,
    ) -> None:
        self._weights = {
            "relevance": relevance_weight,
            "accuracy": accuracy_weight,
            "freshness": freshness_weight,
            "coverage": coverage_weight,
            "redundancy": redundancy_weight,
        }

    def evaluate(
        self,
        entries: list[MemoryEntry],
        context: str = "",
        task_type: str = "",
    ) -> MemoryEvalReport:
        """对记忆库执行全面评估."""
        scores: list[MemoryEvalScore] = []

        scores.append(self._evaluate_relevance(entries, context, task_type))
        scores.append(self._evaluate_accuracy(entries))
        scores.append(self._evaluate_freshness(entries))
        scores.append(self._evaluate_coverage(entries))
        scores.append(self._evaluate_redundancy(entries))

        # 加权总分
        overall = sum(s.score * self._weights.get(s.dimension, 0) for s in scores)

        # 分类统计
        category_dist: dict[str, int] = {}
        for entry in entries:
            cat = entry.category
            category_dist[cat] = category_dist.get(cat, 0) + 1

        # 综合建议
        recommendations = self._generate_recommendations(scores, entries)

        return MemoryEvalReport(
            overall_score=min(1.0, overall),
            scores=scores,
            entry_count=len(entries),
            category_distribution=category_dist,
            recommendations=recommendations,
            generated_at=time.time(),
        )

    def _evaluate_relevance(self, entries: list[MemoryEntry], context: str, task_type: str) -> MemoryEvalScore:
        """评估记忆与当前上下文的相关性."""
        details: list[str] = []
        suggestions: list[str] = []

        if not entries:
            return MemoryEvalScore(
                dimension="relevance",
                score=0.0,
                details=["记忆库为空"],
                suggestions=["建议添加基础偏好记忆"],
            )

        if not context:
            return MemoryEvalScore(
                dimension="relevance",
                score=0.5,
                details=["无评估上下文，使用默认分数"],
            )

        # 基于字符重叠的简单相关性评估（支持中英文）
        context_lower = context.lower()
        relevant_count = 0

        for entry in entries:
            content_lower = entry.content.lower()
            # 检查子串包含（适用于中文）
            if any(word in content_lower for word in context_lower.split()):
                relevant_count += 1
            # 也检查连续子序列匹配
            elif len(context) >= 2:
                # 检查至少2个连续字符是否匹配
                for i in range(len(context) - 1):
                    chunk = context[i : i + 2].lower()
                    if chunk in content_lower:
                        relevant_count += 1
                        break

        relevance_score = relevant_count / len(entries) if entries else 0

        if relevance_score < 0.3:
            suggestions.append("记忆与当前任务相关性较低，建议注入更多相关偏好")
        elif relevance_score > 0.7:
            details.append("记忆高度相关，预计对当前任务有帮助")

        return MemoryEvalScore(
            dimension="relevance",
            score=min(1.0, relevance_score * 1.5),  # 分数加权提升
            details=details,
            suggestions=suggestions,
        )

    def _evaluate_accuracy(self, entries: list[MemoryEntry]) -> MemoryEvalScore:
        """评估记忆的准确性（基于置信度和来源）."""
        if not entries:
            return MemoryEvalScore(dimension="accuracy", score=0.0)

        accuracy_scores: list[float] = []
        for entry in entries:
            base_score = entry.confidence
            # 来源加权
            if entry.source == "user":
                base_score = min(1.0, base_score + 0.1)
            elif entry.source == "system":
                base_score = min(1.0, base_score + 0.05)
            accuracy_scores.append(base_score)

        avg_accuracy = sum(accuracy_scores) / len(accuracy_scores)

        return MemoryEvalScore(
            dimension="accuracy",
            score=avg_accuracy,
            details=[f"平均置信度: {avg_accuracy:.2f}"],
        )

    def _evaluate_freshness(self, entries: list[MemoryEntry]) -> MemoryEvalScore:
        """评估记忆的时效性."""
        if not entries:
            return MemoryEvalScore(dimension="freshness", score=0.0)

        now = time.time()
        ages: list[float] = []
        for entry in entries:
            age_days = (now - entry.updated_at) / 86400
            ages.append(age_days)

        avg_age = sum(ages) / len(ages)
        # 分数: 7天内 = 1.0, 30天 = 0.7, 90天 = 0.3
        if avg_age <= 7:
            score = 1.0
        elif avg_age <= 30:
            score = 0.7
        elif avg_age <= 90:
            score = 0.4
        else:
            score = max(0.1, 1.0 - avg_age / 365)

        return MemoryEvalScore(
            dimension="freshness",
            score=score,
            details=[f"平均记忆年龄: {avg_age:.1f} 天"],
            suggestions=(["建议刷新过时记忆"] if score < 0.5 else []),
        )

    def _evaluate_coverage(self, entries: list[MemoryEntry]) -> MemoryEvalScore:
        """评估记忆覆盖度（类别多样性）."""
        if not entries:
            return MemoryEvalScore(dimension="coverage", score=0.0)

        categories = set(e.category for e in entries)
        expected_categories = {"preference", "history", "fact", "pattern"}
        coverage = len(categories & expected_categories) / len(expected_categories)

        return MemoryEvalScore(
            dimension="coverage",
            score=coverage,
            details=[f"已覆盖类别: {', '.join(sorted(categories))}"],
            suggestions=(["建议添加更多类别记忆"] if coverage < 0.5 else []),
        )

    def _evaluate_redundancy(self, entries: list[MemoryEntry]) -> MemoryEvalScore:
        """评估记忆冗余度."""
        if not entries:
            return MemoryEvalScore(dimension="redundancy", score=0.0)

        # 基于内容相似度的简单检测
        unique_contents: set[str] = set()
        duplicates = 0
        for entry in entries:
            content_key = entry.content.lower().strip()[:100]
            if content_key in unique_contents:
                duplicates += 1
            else:
                unique_contents.add(content_key)

        redundancy_ratio = duplicates / len(entries) if entries else 0
        score = 1.0 - redundancy_ratio  # 越少重复分越高

        return MemoryEvalScore(
            dimension="redundancy",
            score=max(0.0, score),
            details=[f"重复率: {redundancy_ratio:.1%}"],
            suggestions=(["建议清理重复记忆"] if redundancy_ratio > 0.2 else []),
        )

    def _generate_recommendations(self, scores: list[MemoryEvalScore], entries: list[MemoryEntry]) -> list[str]:
        """生成改进建议."""
        recommendations: list[str] = []

        score_map = {s.dimension: s.score for s in scores}

        if score_map.get("relevance", 0) < 0.4:
            recommendations.append("相关性不足: 考虑在用户首次交互时主动询问偏好")
        if score_map.get("freshness", 0) < 0.5:
            recommendations.append("记忆过时: 考虑在每次对话结束时更新记忆")
        if score_map.get("coverage", 0) < 0.5:
            recommendations.append("覆盖度不足: 考虑添加用户事实和行为模式记忆")
        if score_map.get("redundancy", 0) < 0.7:
            recommendations.append("存在冗余: 定期合并相似记忆条目")
        if not entries:
            recommendations.append("记忆库为空: 立即初始化用户基础偏好")

        return recommendations


# ── 便捷函数 ───────────────────────────────────────────────────────────
def quick_eval(entries: list[dict], context: str = "") -> MemoryEvalReport:
    """快速评估（使用字典输入）."""
    framework = MemoryEvalFramework()
    mem_entries = [
        MemoryEntry(
            id=e.get("id", str(i)),
            content=e.get("content", ""),
            category=e.get("category", "fact"),
            created_at=e.get("created_at", time.time()),
            updated_at=e.get("updated_at", time.time()),
            access_count=e.get("access_count", 0),
            confidence=e.get("confidence", 1.0),
            source=e.get("source", "user"),
        )
        for i, e in enumerate(entries)
    ]
    return framework.evaluate(mem_entries, context=context)
