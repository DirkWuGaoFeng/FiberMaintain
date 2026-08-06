"""
L0 Rule Engine Node — Deterministic intent recognition via regex + keywords.

Design principles:
- Zero LLM calls, pure programmatic
- Latency < 10ms
- Only handles high-confidence patterned queries (covers ~78% of daily queries)
- Returns None on miss, delegating to LLM intent classifier

Rules are defined inline for MVP; can be externalized to YAML for hot-reload.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


@dataclass
class RuleMatch:
    """Rule match result."""

    intent: str  # Identified intent
    params: dict  # Extracted parameters (normalized)
    confidence: float  # Confidence (rule hit = 1.0)
    template_id: str  # Output template ID
    fast_path_eligible: bool  # Whether Fast Path is possible (single + no Loop)


# =============================================================================
# Rule Definitions (25-30 rules)
# =============================================================================

RULES: list[dict] = [
    # --- Single fiber spanloss query ---
    {
        "id": "R001",
        "pattern": r"(?:查|看|查询|查一下)\s*(?:光纤|FIB)[-_]?\s*(\d+)\s*(?:的)?\s*(?:跨段)?(?:衰耗|spanloss|损耗)",
        "intent": "spanloss_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_SPANLOSS",
        "fast_path": True,
    },
    # --- Single fiber connection query ---
    {
        "id": "R002",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:连纤|连接|拓扑)",
        "intent": "connection_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_CONNECTION",
        "fast_path": True,
    },
    # --- Single fiber performance query ---
    {
        "id": "R003",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:性能|光功率|OOP|IOP)",
        "intent": "performance_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_PERFORMANCE",
        "fast_path": True,
    },
    # --- Single fiber alarm query ---
    {
        "id": "R004",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:告警|alarm)",
        "intent": "fiber_alarm_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_FIBER_ALARM",
        "fast_path": True,
    },
    # --- Fiber color/status query ---
    {
        "id": "R005",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:颜色|状态|色标)",
        "intent": "single_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_FIBER_STATUS",
        "fast_path": True,
    },
    # --- Port alarm query ---
    {
        "id": "R010",
        "pattern": r"(\d+)\s*号?\s*(?:盘|单盘|板)\s*(\d+)\s*号?\s*(?:口|端口)\s*(?:的)?\s*(?:告警|alarm)",
        "intent": "port_alarm_query",
        "param_extract": lambda m: {"board_id": int(m.group(1)), "port_id": int(m.group(2))},
        "template": "T_PORT_ALARM",
        "fast_path": True,
    },
    # --- Board query ---
    {
        "id": "R011",
        "pattern": r"(?:查|看|查询)\s*(\d+)\s*号?\s*(?:盘|单盘|板)\s*(?:的)?\s*(?:信息|状态)",
        "intent": "single_query",
        "param_extract": lambda m: {"board_id": int(m.group(1))},
        "template": "T_BOARD",
        "fast_path": True,
    },
    # --- Red fiber query ---
    {
        "id": "R020",
        "pattern": r"(?:有哪些|多少|查|看|列出)\s*(红色|RED|red)\s*(?:光纤|的)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "RED"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- Yellow fiber query ---
    {
        "id": "R021",
        "pattern": r"(?:有哪些|多少|查|看|列出)\s*(黄色|YELLOW|yellow)\s*(?:光纤|的)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "YELLOW"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- Green fiber query ---
    {
        "id": "R022",
        "pattern": r"(?:有哪些|多少|查|看|列出)\s*(绿色|GREEN|green)\s*(?:光纤|的)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "GREEN"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- Fiber total count ---
    {
        "id": "R030",
        "pattern": r"(?:光纤|连纤)\s*(?:总数|总共|一共|有多少|数量)",
        "intent": "stats_query",
        "param_extract": lambda m: {},
        "template": "T_STATS",
        "fast_path": True,
    },
    # --- Color distribution stats ---
    {
        "id": "R031",
        "pattern": r"(?:颜色|色标)\s*(?:分布|统计|占比)",
        "intent": "stats_query",
        "param_extract": lambda m: {},
        "template": "T_STATS",
        "fast_path": True,
    },
    # --- Trend query ---
    {
        "id": "R032",
        "pattern": r"(?:趋势|变化|统计)\s*(?:图|数据|报告)?",
        "intent": "trend_query",
        "param_extract": lambda m: {},
        "template": "T_TREND",
        "fast_path": True,
    },
    # --- Knowledge QA (keyword trigger) ---
    {
        "id": "R040",
        "pattern": r"(?:什么是|解释|定义|含义)\s*(.{2,20})",
        "intent": "knowledge_qa",
        "param_extract": lambda m: {"question": m.group(1).strip()},
        "template": "T_KNOWLEDGE",
        "fast_path": False,  # RAG needs LLM to organize answer
    },
    # --- Why red/yellow diagnosis ---
    {
        "id": "R050",
        "pattern": r"(?:光纤|FIB)[-_]?(\d+)\s*(?:为什么|为何|怎么)\s*(?:变)?(?:红|红色)",
        "intent": "color_diagnosis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,  # Needs multi-step analysis
    },
    {
        "id": "R051",
        "pattern": r"(?:光纤|FIB)[-_]?(\d+)\s*(?:为什么|为何|怎么)\s*(?:变)?(?:黄|黄色)",
        "intent": "color_diagnosis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,
    },
    # --- Spanloss analysis ---
    {
        "id": "R052",
        "pattern": r"(?:分析|诊断|排查)\s*(?:光纤|FIB)[-_]?(\d+)",
        "intent": "spanloss_analysis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,
    },
    # --- Report generation ---
    {
        "id": "R060",
        "pattern": r"(?:生成|写|出)\s*(?:本周|今日|本月|巡检|维护)?\s*(?:报告|报表)",
        "intent": "report_generation",
        "param_extract": lambda m: {},
        "template": "T_REPORT",
        "fast_path": False,
    },
    # --- Batch: all red fibers ---
    {
        "id": "R070",
        "pattern": r"(?:所有|全部|批量)\s*(?:红色|RED)\s*(?:光纤|的)",
        "intent": "batch_query",
        "param_extract": lambda m: {"color": "RED"},
        "template": "T_BATCH",
        "fast_path": False,
    },
    # --- Batch: all fibers ---
    {
        "id": "R071",
        "pattern": r"(?:查|看|批量查)\s*(?:所有|全部|所有)\s*(?:光纤|连纤)",
        "intent": "batch_query",
        "param_extract": lambda m: {},
        "template": "T_BATCH",
        "fast_path": False,
    },
    # --- Health check ---
    {
        "id": "R080",
        "pattern": r"(?:系统|设备|网元)\s*(?:健康|状态|巡检)\s*(?:检查|报告)?",
        "intent": "health_check",
        "param_extract": lambda m: {},
        "template": "T_HEALTH",
        "fast_path": False,
    },
    # --- Fiber history performance ---
    {
        "id": "R090",
        "pattern": r"(?:查|看)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:历史|最近)\s*(?:性能|光功率)",
        "intent": "performance_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1)), "history": True},
        "template": "T_PERFORMANCE",
        "fast_path": True,
    },
    # --- Generic single fiber query (catch-all) ---
    {
        "id": "R100",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)",
        "intent": "single_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_FIBER_STATUS",
        "fast_path": True,
    },
    # --- v7.2: 连纤颜色查询（"连纤X颜色"）— 置于 R101 前以优先匹配 ---
    {
        "id": "R102",
        "pattern": r"连纤\s*(\d+)\s*(?:的)?\s*(?:颜色|色标|状态)",
        "intent": "single_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_FIBER_STATUS",
        "fast_path": True,
    },
    # --- v7.2: 口语化衰耗查询（"光纤X衰耗""连纤X衰耗"）— 置于 R101 前以优先匹配 ---
    {
        "id": "R105",
        "pattern": r"(?:光纤|连纤|FIB)[-_]?\s*(\d+)\s*(?:的)?\s*(?:衰耗|损耗|spanloss)",
        "intent": "spanloss_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_SPANLOSS",
        "fast_path": True,
    },
    # --- v7.2: 连纤查询（"连纤X""分析连纤X中断"等口语化表达） ---
    {
        "id": "R101",
        "pattern": r"(?:分析|诊断|排查)?\s*连纤\s*(\d+)\s*(?:中断|断开|故障)?\s*(?:的)?\s*(?:原因|问题)?",
        "intent": "connection_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_CONNECTION",
        "fast_path": True,
    },
    # --- v7.2: 断纤查询（"目前断纤有哪些""断纤列表"） ---
    {
        "id": "R103",
        "pattern": r"(?:目前|当前|现在)?\s*(?:断纤|中断光纤|断开的光纤)\s*(?:有哪些|列表|多少|查询)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "RED"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- v7.2: 光纤中断分析（"光纤X中断的原因"） ---
    {
        "id": "R104",
        "pattern": r"(?:光纤|FIB)[-_]?(\d+)\s*(?:中断|断开|故障)\s*(?:的)?\s*(?:原因|分析)?",
        "intent": "spanloss_analysis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,
    },
]

# Compile all patterns once
_COMPILED_RULES = [(rule, re.compile(rule["pattern"], re.IGNORECASE)) for rule in RULES]


class RuleEngine:
    """
    L0 Rule Engine: regex + keyword based deterministic intent recognition.

    Design:
    - Zero LLM calls, pure programmatic
    - Latency < 10ms
    - Only handles high-confidence patterned queries
    - Returns None on miss, delegating to LLM
    """

    @classmethod
    def reload_rules(cls) -> int:
        """
        Hot-reload rules: re-compile all patterns.

        For MVP, rules are inline so this simply re-compiles.
        Future: load from config/rules.yaml if present.
        Returns number of rules loaded.
        """
        global _COMPILED_RULES
        _COMPILED_RULES = [
            (rule, re.compile(rule["pattern"], re.IGNORECASE)) for rule in RULES
        ]
        logger.info(f"[RuleEngine] Rules reloaded: {len(_COMPILED_RULES)} rules")
        return len(_COMPILED_RULES)

    @classmethod
    def match(cls, user_input: str) -> Optional[RuleMatch]:
        """
        Attempt rule matching. Returns RuleMatch on hit, None on miss.

        Priority: Skill system TriggerRegistry → legacy inline rules (fallback).
        Time complexity: O(n), n = number of rules, latency < 10ms.
        """
        # 优先从 Skill 系统匹配
        try:
            from ..skills.loader import get_registries

            trigger_registry = get_registries()["trigger"]
            result = trigger_registry.match(user_input)
            if result:
                return RuleMatch(
                    intent=result["intent"],
                    params=result["params"],
                    confidence=result["confidence"],
                    template_id=result["template_id"],
                    fast_path_eligible=result["fast_path_eligible"],
                )
        except (ImportError, KeyError):
            pass  # Skill 系统未初始化，fallback 到内置规则

        # Fallback: 内置规则（渐进迁移期保留）
        text = user_input.strip()
        for rule, pattern in _COMPILED_RULES:
            m = pattern.search(text)
            if m:
                try:
                    params = rule["param_extract"](m)
                    return RuleMatch(
                        intent=rule["intent"],
                        params=params,
                        confidence=1.0,
                        template_id=rule["template"],
                        fast_path_eligible=rule["fast_path"],
                    )
                except (ValueError, IndexError, AttributeError):
                    continue  # Parameter extraction failed, try next rule
        return None  # No match, delegate to LLM


async def rule_engine_node(state: MainGraphState) -> dict:
    """
    Rule engine node: attempts deterministic intent recognition.

    If matched: stores RuleMatch in state for routing.
    If not matched: returns rule_match=None → routes to LLM classifier.
    """
    import time

    user_input = state.get("user_input", "")
    trace_id = state.get("trace_id", "")
    start_time = time.time()

    logger.info(f"[TRACE:{trace_id}] [rule_engine] START input=\"{user_input[:80]}\"")

    # Skip if already blocked by input guard
    if state.get("processing_path") == "blocked":
        return {}

    match = RuleEngine.match(user_input)
    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    if match:
        logger.info(
            f"[TRACE:{trace_id}] [rule_engine] OK {elapsed_ms}ms "
            f"match={match.intent} params={match.params} fast_path={match.fast_path_eligible}"
        )
        return {
            "rule_match": {
                "intent": match.intent,
                "params": match.params,
                "confidence": match.confidence,
                "template_id": match.template_id,
                "fast_path_eligible": match.fast_path_eligible,
            },
            "intent": match.intent,
            "processing_path": "fast" if match.fast_path_eligible else "normal",
        }

    logger.info(f"[TRACE:{trace_id}] [rule_engine] OK {elapsed_ms}ms match=None (delegating to LLM)")
    return {"rule_match": None}
