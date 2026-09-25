"""
规则引擎节点 —— 基于正则 + 关键词的确定性意图识别（L0 层）。

【设计原则】
- 零 LLM 调用，纯程序化匹配
- 延迟 < 10ms（25-30 条正则规则顺序匹配）
- 仅处理高置信度的模式化查询（覆盖约 78% 的日常查询）
- 未命中时返回 None，交给 LLM 意图分类器处理

【规则定义】
规则以内联方式定义在 RULES 列表中（MVP 阶段）。
未来可外置到 config/rules.yaml 实现热更新。

【面试知识点】
  Q: 为什么规则引擎不直接用 LLM？
  A: ① 延迟差异巨大（10ms vs 2-5s）；② 零 token 成本；
     ③ 确定性输出，相同输入必定相同结果；
     ④ 可单元测试，不依赖模型版本。
  Q: 规则引擎和 Skill 系统的 TriggerRegistry 是什么关系？
  A: Skill 系统是规则引擎的升级替代，优先匹配 Skill 注册表，
     未命中时 fallback 到内置正则规则，支持渐进迁移。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


@dataclass
class RuleMatch:
    """规则匹配结果。

    【字段说明】
    - intent: 识别出的意图类型（如 spanloss_query, colored_query）
    - params: 从用户输入中提取并归一化的参数（如 {"fiber_id": 12}）
    - confidence: 置信度（规则命中固定为 1.0，因为正则是确定性匹配）
    - template_id: 输出模板 ID（如 T_SPANLOSS），用于快速路径渲染
    - fast_path_eligible: 是否满足快速路径条件（单条查询 + 无需循环分析）
    """

    intent: str  # 识别出的意图类型
    params: dict  # 提取的参数（已归一化）
    confidence: float  # 置信度（规则命中 = 1.0）
    template_id: str  # 输出模板 ID
    fast_path_eligible: bool  # 是否可走快速路径（跳过 LLM）


# =============================================================================
# 规则定义（25-30 条）
# 【面试知识点】规则按优先级排列，越具体的规则越靠前。
# 例如 R102（连纤X颜色）必须在 R100（通用单纤查询）之前，
# 否则 "连纤1颜色" 会被 R100 先匹配为普通查询。
# =============================================================================

RULES: list[dict] = [
    # --- 单条光纤衰耗查询 ---
    {
        "id": "R001",
        "pattern": r"(?:查|看|查询|查一下)\s*(?:光纤|FIB)[-_]?\s*(\d+)\s*(?:的)?\s*(?:跨段)?(?:衰耗|spanloss|损耗)",
        "intent": "spanloss_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_SPANLOSS",
        "fast_path": True,
    },
    # --- 单条光纤连纤查询 ---
    {
        "id": "R002",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:连纤|连接|拓扑)",
        "intent": "connection_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_CONNECTION",
        "fast_path": True,
    },
    # --- 单条光纤性能查询 ---
    {
        "id": "R003",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:性能|光功率|OOP|IOP)",
        "intent": "performance_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_PERFORMANCE",
        "fast_path": True,
    },
    # --- 单条光纤告警查询 ---
    {
        "id": "R004",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:告警|alarm)",
        "intent": "fiber_alarm_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_FIBER_ALARM",
        "fast_path": True,
    },
    # --- 光纤颜色/状态查询 ---
    {
        "id": "R005",
        "pattern": r"(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:颜色|状态|色标)",
        "intent": "single_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_FIBER_STATUS",
        "fast_path": True,
    },
    # --- 端口告警查询 ---
    {
        "id": "R010",
        "pattern": r"(\d+)\s*号?\s*(?:盘|单盘|板)\s*(\d+)\s*号?\s*(?:口|端口)\s*(?:的)?\s*(?:告警|alarm)",
        "intent": "port_alarm_query",
        "param_extract": lambda m: {"board_id": int(m.group(1)), "port_id": int(m.group(2))},
        "template": "T_PORT_ALARM",
        "fast_path": True,
    },
    # --- 单盘查询 ---
    {
        "id": "R011",
        "pattern": r"(?:查|看|查询)\s*(\d+)\s*号?\s*(?:盘|单盘|板)\s*(?:的)?\s*(?:信息|状态)",
        "intent": "single_query",
        "param_extract": lambda m: {"board_id": int(m.group(1))},
        "template": "T_BOARD",
        "fast_path": True,
    },
    # --- 红色光纤查询 ---
    {
        "id": "R020",
        "pattern": r"(?:有哪些|多少|查|看|列出)\s*(红色|RED|red)\s*(?:光纤|的)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "RED"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- 黄色光纤查询 ---
    {
        "id": "R021",
        "pattern": r"(?:有哪些|多少|查|看|列出)\s*(黄色|YELLOW|yellow)\s*(?:光纤|的)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "YELLOW"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- 绿色光纤查询 ---
    {
        "id": "R022",
        "pattern": r"(?:有哪些|多少|查|看|列出)\s*(绿色|GREEN|green)\s*(?:光纤|的)?",
        "intent": "colored_query",
        "param_extract": lambda m: {"color": "GREEN"},
        "template": "T_COLORED",
        "fast_path": True,
    },
    # --- 光纤总数 ---
    {
        "id": "R030",
        "pattern": r"(?:光纤|连纤)\s*(?:总数|总共|一共|有多少|数量)",
        "intent": "stats_query",
        "param_extract": lambda m: {},
        "template": "T_STATS",
        "fast_path": True,
    },
    # --- 颜色分布统计 ---
    {
        "id": "R031",
        "pattern": r"(?:颜色|色标)\s*(?:分布|统计|占比)",
        "intent": "stats_query",
        "param_extract": lambda m: {},
        "template": "T_STATS",
        "fast_path": True,
    },
    # --- 趋势查询 ---
    {
        "id": "R032",
        "pattern": r"(?:趋势|变化|统计)\s*(?:图|数据|报告)?",
        "intent": "trend_query",
        "param_extract": lambda m: {},
        "template": "T_TREND",
        "fast_path": True,
    },
    # --- 知识问答（关键词触发） ---
    {
        "id": "R040",
        "pattern": r"(?:什么是|解释|定义|含义)\s*(.{2,20})",
        "intent": "knowledge_qa",
        "param_extract": lambda m: {"question": m.group(1).strip()},
        "template": "T_KNOWLEDGE",
        "fast_path": False,  # RAG 需要 LLM 组织答案
    },
    # --- 红/黄原因诊断 ---
    {
        "id": "R050",
        "pattern": r"(?:光纤|FIB)[-_]?(\d+)\s*(?:为什么|为何|怎么)\s*(?:变)?(?:红|红色)",
        "intent": "color_diagnosis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,  # 需要多步分析
    },
    {
        "id": "R051",
        "pattern": r"(?:光纤|FIB)[-_]?(\d+)\s*(?:为什么|为何|怎么)\s*(?:变)?(?:黄|黄色)",
        "intent": "color_diagnosis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,
    },
    # --- 衰耗分析 ---
    {
        "id": "R052",
        "pattern": r"(?:分析|诊断|排查)\s*(?:光纤|FIB)[-_]?(\d+)",
        "intent": "spanloss_analysis",
        "param_extract": lambda m: {"fiber_id": int(m.group(1))},
        "template": "T_DIAGNOSIS",
        "fast_path": False,
    },
    # --- 报告生成 ---
    {
        "id": "R060",
        "pattern": r"(?:生成|写|出)\s*(?:本周|今日|本月|巡检|维护)?\s*(?:报告|报表)",
        "intent": "report_generation",
        "param_extract": lambda m: {},
        "template": "T_REPORT",
        "fast_path": False,
    },
    # --- 批量：所有红色光纤 ---
    {
        "id": "R070",
        "pattern": r"(?:所有|全部|批量)\s*(?:红色|RED)\s*(?:光纤|的)",
        "intent": "batch_query",
        "param_extract": lambda m: {"color": "RED"},
        "template": "T_BATCH",
        "fast_path": False,
    },
    # --- 批量：所有光纤 ---
    {
        "id": "R071",
        "pattern": r"(?:查|看|批量查)\s*(?:所有|全部|所有)\s*(?:光纤|连纤)",
        "intent": "batch_query",
        "param_extract": lambda m: {},
        "template": "T_BATCH",
        "fast_path": False,
    },
    # --- 健康检查 ---
    {
        "id": "R080",
        "pattern": r"(?:系统|设备|网元)\s*(?:健康|状态|巡检)\s*(?:检查|报告)?",
        "intent": "health_check",
        "param_extract": lambda m: {},
        "template": "T_HEALTH",
        "fast_path": False,
    },
    # --- 光纤历史性能 ---
    {
        "id": "R090",
        "pattern": r"(?:查|看)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:历史|最近)\s*(?:性能|光功率)",
        "intent": "performance_query",
        "param_extract": lambda m: {"fiber_id": int(m.group(1)), "history": True},
        "template": "T_PERFORMANCE",
        "fast_path": True,
    },
    # --- 通用单条光纤查询（兜底） ---
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
    # --- v7.2: 断纤查询（"目前断纤有哪些""查询所有中断连纤信息""断纤列表"） ---
    {
        "id": "R103",
        "pattern": r"(?:查询|查|看)?\s*(?:所有|全部)?\s*(?:断纤|中断光纤|中断连纤|断开的光纤)\s*(?:有哪些|列表|多少|查询|信息)?",
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

# 预编译所有正则表达式（模块加载时一次性完成，避免重复编译）
_COMPILED_RULES = [(rule, re.compile(rule["pattern"], re.IGNORECASE)) for rule in RULES]


class RuleEngine:
    """L0 规则引擎：基于正则 + 关键词的确定性意图识别。

    【设计要点】
    - 零 LLM 调用，纯程序化，延迟 < 10ms
    - 仅处理高置信度的模式化查询
    - 未命中时返回 None，委托给 LLM 意图分类器

    【面试知识点】
    - 类方法（@classmethod）使规则引擎无需实例化即可使用
    - 预编译正则（re.compile）是性能优化关键，避免每次匹配重新编译
    """

    @classmethod
    def reload_rules(cls) -> int:
        """热重载规则：重新编译所有正则模式。

        【功能说明】
        MVP 阶段规则为内联定义，此方法仅重新编译。
        未来可从 config/rules.yaml 加载规则实现运行时热更新。

        【返回值】
            加载的规则数量
        """
        global _COMPILED_RULES
        _COMPILED_RULES = [(rule, re.compile(rule["pattern"], re.IGNORECASE)) for rule in RULES]
        logger.info(f"[RuleEngine] Rules reloaded: {len(_COMPILED_RULES)} rules")
        return len(_COMPILED_RULES)

    @classmethod
    def match(cls, user_input: str) -> Optional[RuleMatch]:
        """尝试规则匹配，命中返回 RuleMatch，未命中返回 None。

        【匹配优先级】
        1. 优先从 Skill 系统的 TriggerRegistry 匹配
        2. 未命中则 fallback 到内置正则规则（渐进迁移期保留）

        【时间复杂度】O(n)，n = 规则数量，延迟 < 10ms

        【参数说明】
            user_input: 用户原始输入文本

        【返回值】
            RuleMatch 对象（命中）或 None（未命中，交给 LLM）
        """
        # 复合查询检测：如果输入包含多个意图关键词，不走快速路径
        # 让 LLM 处理复合查询，避免规则引擎只处理部分意图
        if cls._is_complex_query(user_input):
            logger.info(f"[RuleEngine] Complex query detected, delegating to LLM: {user_input[:50]}...")
            return None

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
                    continue  # 参数提取失败，尝试下一条规则
        return None  # 未命中，交给 LLM 处理

    @classmethod
    def _is_complex_query(cls, text: str) -> bool:
        """检测是否为复合查询（包含多个意图）。

        【功能说明】
        复合查询特征：
        - 包含顿号"、"分隔多个查询项
        - 包含"并"、"和"、"以及"等连接词
        - 包含"并"字且后面有分析类动词

        【设计约束】
        v7.2 起，R101/R104/R050-R052 已精确覆盖"分析/诊断/排查
        光纤/连纤X（中断/故障）的原因"等口语化分析查询，因此不再用
        "分析.*原因" 宽泛启发式把这类单意图查询误判为复合查询，
        否则 R101/R104 永远无法命中（v7.2 回归测试要求其走确定性规则）。

        【返回值】
            True: 复合查询，应交给 LLM 处理
            False: 简单查询，可走快速路径
        """
        # 顿号分隔多个查询项（如"告警、性能、衰耗"）
        if "、" in text:
            return True

        # 连接词连接多个意图
        if re.search(r"(?:并|和|以及|同时|另外).*(?:查询|分析|诊断|查看|检查)", text):
            return True

        # 包含"并"字且后面有分析类动词
        if "并" in text and re.search(r"并\s*(?:分析|诊断|排查|评估)", text):
            return True

        return False


async def rule_engine_node(state: MainGraphState) -> dict:
    """规则引擎节点：尝试确定性意图识别。

    【节点职责】
    - 命中规则：将 RuleMatch 存入状态，供后续路由决策
    - 未命中：返回 rule_match=None → 路由到 LLM 意图分类器

    【输入】state.user_input（用户原始文本）
    【输出】rule_match（RuleMatch 序列化 dict 或 None）
    【状态更新】intent, processing_path（fast/normal）
    """
    import time

    user_input = state.get("user_input", "")
    trace_id = state.get("trace_id", "")
    start_time = time.time()

    logger.info(f'[TRACE:{trace_id}] [rule_engine] START input="{user_input[:80]}"')

    # 如果已被输入守卫拦截则跳过
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
