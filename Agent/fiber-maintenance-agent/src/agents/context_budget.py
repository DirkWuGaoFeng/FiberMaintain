"""
Phase 4.1: 上下文预算管理

总预算 8192 tokens: 固定区 1300 + 弹性区 4892 + 输出预留 2000
弹性区优先级: P1数据(3000) > P2 RAG(1000) > P3记忆(500)
超限降级树: P3(3->1->0) -> P2(3->2->1->0) -> P1(全量->聚合Top10->最小Top5)
TokenEstimator: 中文1.5字/token, 英文4字符/token, JSON 3字符/token
各 Agent 差异化预算
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fiber.budget")


# ============================================================
#  TokenEstimator — 估算 token 数
# ============================================================

class TokenEstimator:
    """快速 token 估算器（无需调用 tokenizer API）。"""

    @staticmethod
    def estimate(text: str | dict | list) -> int:
        if isinstance(text, (dict, list)):
            return TokenEstimator._estimate_json(text)
        if not isinstance(text, str):
            text = str(text)
        # 中文: ~1.5 tokens/字符
        cn = len(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text))
        # 英文单词
        en = len(re.findall(r'[a-zA-Z]+', text))
        # 数字
        nums = len(re.findall(r'\d+\.?\d*', text))
        # 其他字符
        other = len(text) - cn - sum(len(w) for w in re.findall(r'[a-zA-Z]+', text)) - sum(len(w) for w in re.findall(r'\d+\.?\d*', text))
        return int(cn * 1.5 + en + nums + max(other, 0) * 0.5)

    @staticmethod
    def _estimate_json(obj: Any) -> int:
        """JSON 对象/数组: ~3 字符/token。"""
        import json
        try:
            s = json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:
            s = str(obj)
        return max(1, len(s) // 3)


_estimator = TokenEstimator()


# ============================================================
#  BudgetConfig — 预算配置
# ============================================================

@dataclass
class BudgetConfig:
    """Agent 预算配置。"""
    total: int = 8192
    fixed: int = 1300         # system prompt + tools
    output_reserve: int = 2000
    p1_data: int = 3000       # 工具返回数据
    p2_rag: int = 1000        # RAG 知识注入
    p3_memory: int = 500      # 记忆上下文

    @property
    def elastic(self) -> int:
        return self.total - self.fixed - self.output_reserve

    def validate(self) -> bool:
        return self.p1_data + self.p2_rag + self.p3_memory <= self.elastic


# Agent 差异化预算
AGENT_BUDGETS: dict[str, BudgetConfig] = {
    "lead": BudgetConfig(total=8192, fixed=1500, output_reserve=2000,
                         p1_data=2692, p2_rag=1000, p3_memory=500),
    "data-collector": BudgetConfig(total=8192, fixed=1000, output_reserve=1500,
                                   p1_data=4692, p2_rag=500, p3_memory=500),
    "analysis-expert": BudgetConfig(total=8192, fixed=1300, output_reserve=2500,
                                    p1_data=2892, p2_rag=1000, p3_memory=500),
    "knowledge-assistant": BudgetConfig(total=8192, fixed=1200, output_reserve=2000,
                                        p1_data=1492, p2_rag=2500, p3_memory=1000),
    "report-generator": BudgetConfig(total=8192, fixed=1300, output_reserve=3000,
                                     p1_data=2392, p2_rag=1000, p3_memory=500),
}


def get_budget(agent_name: str) -> BudgetConfig:
    return AGENT_BUDGETS.get(agent_name, BudgetConfig())


# ============================================================
#  ContextBudget — 预算管理器
# ============================================================

@dataclass
class BudgetAllocation:
    """预算分配结果。"""
    data_items: list[Any] = field(default_factory=list)
    rag_items: list[dict] = field(default_factory=list)
    memory_items: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    overflow: bool = False
    degradation_log: list[str] = field(default_factory=list)


class ContextBudget:
    """上下文预算管理器：分配 + 超限降级。"""

    def __init__(self, config: BudgetConfig | None = None):
        self._cfg = config or BudgetConfig()
        self._est = _estimator

    def allocate(
        self,
        data_items: list[Any] | None = None,
        rag_items: list[dict] | None = None,
        memory_items: list[dict] | None = None,
    ) -> BudgetAllocation:
        """分配预算，超限时按降级策略裁剪。"""
        alloc = BudgetAllocation()
        data_items = data_items or []
        rag_items = rag_items or []
        memory_items = memory_items or []

        # 1) 先尝试全量
        data_tokens = sum(self._est.estimate(d) for d in data_items)
        rag_tokens = sum(self._est.estimate(r) for r in rag_items)
        mem_tokens = sum(self._est.estimate(m) for m in memory_items)
        total = data_tokens + rag_tokens + mem_tokens

        if total <= self._cfg.elastic:
            alloc.data_items = data_items
            alloc.rag_items = rag_items
            alloc.memory_items = memory_items
            alloc.total_tokens = total
            return alloc

        alloc.overflow = True
        logger.info("Budget overflow: %d > %d, 启动降级",
                     total, self._cfg.elastic)

        # 2) 降级树: P3(3->1->0) -> P2(3->2->1->0) -> P1(全量->Top10->Top5)
        alloc.memory_items = self._degrade_p3(memory_items, alloc)
        if self._check_fit(alloc, data_items, rag_items):
            return self._finalize(alloc, data_items, rag_items)

        alloc.rag_items = self._degrade_p2(rag_items, alloc)
        if self._check_fit(alloc, data_items, alloc.rag_items):
            return self._finalize(alloc, data_items, alloc.rag_items)

        alloc.data_items = self._degrade_p1(data_items, alloc)
        return self._finalize(alloc, alloc.data_items, alloc.rag_items)

    def _check_fit(self, alloc: BudgetAllocation,
                   data: list, rag: list) -> bool:
        t = (sum(self._est.estimate(d) for d in data)
             + sum(self._est.estimate(r) for r in rag)
             + sum(self._est.estimate(m) for m in alloc.memory_items))
        return t <= self._cfg.elastic

    def _finalize(self, alloc: BudgetAllocation,
                  data: list, rag: list) -> BudgetAllocation:
        alloc.data_items = data
        alloc.rag_items = rag
        alloc.total_tokens = (
            sum(self._est.estimate(d) for d in data)
            + sum(self._est.estimate(r) for r in rag)
            + sum(self._est.estimate(m) for m in alloc.memory_items))
        logger.info("Budget allocated: %d tokens (overflow=%s, degradations=%s)",
                     alloc.total_tokens, alloc.overflow, alloc.degradation_log)
        return alloc

    # ── 降级策略 ──

    def _degrade_p3(self, items: list[dict],
                    alloc: BudgetAllocation) -> list[dict]:
        """P3 记忆: 3条 → 1条 → 0条。"""
        for limit, label in [(3, "P3:3"), (1, "P3:1"), (0, "P3:0")]:
            truncated = items[:limit]
            tokens = sum(self._est.estimate(m) for m in truncated)
            if tokens <= self._cfg.p3_memory or limit == 0:
                alloc.degradation_log.append(f"{label}(tokens={tokens})")
                return truncated
        return []

    def _degrade_p2(self, items: list[dict],
                    alloc: BudgetAllocation) -> list[dict]:
        """P2 RAG: 全部 → 3条 → 2条 → 1条 → 0条。"""
        for limit, label in [(len(items), "P2:full"), (3, "P2:3"),
                             (2, "P2:2"), (1, "P2:1"), (0, "P2:0")]:
            truncated = items[:limit]
            tokens = sum(self._est.estimate(r) for r in truncated)
            if tokens <= self._cfg.p2_rag or limit == 0:
                alloc.degradation_log.append(f"{label}(tokens={tokens})")
                return truncated
        return []

    def _degrade_p1(self, items: list[Any],
                    alloc: BudgetAllocation) -> list[Any]:
        """P1 数据: 全量 → Top10聚合 → Top5最小。"""
        if not items:
            return items

        total_tokens = sum(self._est.estimate(d) for d in items)

        # 全量可接受?
        if total_tokens <= self._cfg.p1_data:
            alloc.degradation_log.append(f"P1:full(tokens={total_tokens})")
            return items

        # Top 10 聚合
        if len(items) > 10:
            top10 = items[:10]
            t10 = sum(self._est.estimate(d) for d in top10)
            if t10 <= self._cfg.p1_data:
                alloc.degradation_log.append(f"P1:top10(tokens={t10})")
                return top10

        # Top 5 最小
        top5 = items[:5]
        t5 = sum(self._est.estimate(d) for d in top5)
        alloc.degradation_log.append(f"P1:top5(tokens={t5})")
        return top5
