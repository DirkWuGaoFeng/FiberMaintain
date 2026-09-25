"""
参数门禁节点 —— Layer 2 验证与归一化。

【功能说明】
将用户原始表达式转换为后端兼容的强类型：
- "FIB-0012" → 12，"13号光纤" → 13，"5号盘" → 5
- 颜色映射："红色" → "RED"
- 时间解析："最近一周" → ISO 8601 时间范围

纯程序化，零 LLM 调用，延迟 < 5ms。

【面试知识点】
  Q: 为什么需要参数归一化？
  A: 用户输入格式不固定（"FIB-0012"、"12号光纤"、"光纤12"），
     后端需要统一的 int32 类型。归一化是防御性编程的体现，
     避免无效参数穿透到后端导致 500 错误。
  Q: 三层防御体系是什么？
  A: Layer 1 = InputGuard（安全过滤）；
     Layer 2 = ParamGate（类型归一化）；
     Layer 3 = 后端自身的参数校验。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from ..config import ALARM_BATCH_MAX, BATCH_MAX_TOTAL
from ..graph.state import MainGraphState, NormalizedParams

logger = logging.getLogger(__name__)

# =============================================================================
# 意图级必需参数映射
# 【设计说明】某些意图必须携带特定参数才能执行，缺少时应触发澄清追问，
# 而非让 LLM 幻觉填充默认值（如默认查光纤1）。
# =============================================================================
_INTENT_REQUIRED_PARAMS: dict[str, list[str]] = {
    # 光纤级查询：必须有 fiber_id
    "spanloss_query": ["fiber_ids"],
    "spanloss_analysis": ["fiber_ids"],
    "connection_query": ["fiber_ids"],
    "performance_query": ["fiber_ids"],
    "fiber_alarm_query": ["fiber_ids"],
    "single_query": ["fiber_ids"],
    "trend_analysis": ["fiber_ids"],
    "color_diagnosis": ["fiber_ids"],
    # 端口告警查询：必须有 board_id + port_id
    "port_alarm_query": ["board_ids", "port_ids"],
}

# 必需参数缺失时的友好提示文本
_REQUIRED_PARAM_HINT: dict[str, str] = {
    "fiber_ids": "未指定光纤编号（示例：查询光纤1的衰耗）",
    "board_ids": "未指定单盘编号（示例：2号盘）",
    "port_ids": "未指定端口编号（示例：3号口）",
}


class ParamGate:
    """参数验证门禁：将原始表达式转换为精确的后端类型。

    【三层防御】Layer 2：
    ① 格式转换（正则模式匹配多种用户表述）
    ② 业务规则（fiber_id > 0，批量上限 ≤ 200）
    ③ 枚举校验（color ∈ {RED, YELLOW, GREEN}）
    """

    # ===== 格式转换模式 =====
    # 【设计说明】每种 ID 支持多种用户表述格式，按特异性排列
    _FIBER_PATTERNS = [
        (r"^FIB[-_]?(\d+)$", lambda m: int(m.group(1))),
        (r"^fiber[-_\s]?(\d+)$", lambda m: int(m.group(1))),
        (r"(\d+)\s*号?\s*光纤", lambda m: int(m.group(1))),
        (r"光纤\s*[#:]?\s*(\d+)", lambda m: int(m.group(1))),
        (r"^(\d+)$", lambda m: int(m.group(1))),
    ]

    _BOARD_PATTERNS = [
        (r"^board[-_\s]?(\d+)$", lambda m: int(m.group(1))),
        (r"(\d+)\s*号?\s*(?:盘|单盘|板)", lambda m: int(m.group(1))),
        (r"^(\d+)$", lambda m: int(m.group(1))),
    ]

    _PORT_PATTERNS = [
        (r"^port[-_\s]?(\d+)$", lambda m: int(m.group(1))),
        (r"(\d+)\s*号?\s*(?:口|端口)", lambda m: int(m.group(1))),
        (r"^(\d+)$", lambda m: int(m.group(1))),
    ]

    _COLOR_MAP = {
        "红色": "RED",
        "红": "RED",
        "red": "RED",
        "黄色": "YELLOW",
        "黄": "YELLOW",
        "yellow": "YELLOW",
        "绿色": "GREEN",
        "绿": "GREEN",
        "green": "GREEN",
    }

    @classmethod
    def validate_and_normalize(cls, raw: dict) -> NormalizedParams:
        """Layer 2：验证并归一化原始参数。

        【功能说明】
        处理流程：光纤ID → 单盘ID → 端口ID → 颜色 → 时间 → 网元ID
        每一步都收集解析失败信息，最终统一返回。

        【参数说明】
            raw: 原始提取结果（来自规则引擎或 LLM 意图分类器）

        【返回值】
            NormalizedParams（强类型，与后端 int32/enum 对齐）
        """
        failures: list[str] = []

        # 光纤 ID
        fiber_ids: list[int] = []
        for ref in raw.get("fiber_refs", []):
            fid = cls._extract_id(str(ref), cls._FIBER_PATTERNS)
            if fid is not None and fid > 0:
                fiber_ids.append(fid)
            else:
                failures.append(f"无法识别光纤标识: '{ref}'（示例: FIB-0012 或 12号光纤）")

        # 同时处理直接的 fiber_id 参数
        if raw.get("fiber_id"):
            fid = cls._extract_id(str(raw["fiber_id"]), cls._FIBER_PATTERNS)
            if fid and fid > 0 and fid not in fiber_ids:
                fiber_ids.append(fid)

        # 批量上限
        if len(fiber_ids) > BATCH_MAX_TOTAL:
            failures.append(f"批量上限 {BATCH_MAX_TOTAL} 条，当前 {len(fiber_ids)} 条")
            fiber_ids = fiber_ids[:BATCH_MAX_TOTAL]

        # 单盘 ID
        board_ids: list[int] = []
        for ref in raw.get("board_refs", []):
            bid = cls._extract_id(str(ref), cls._BOARD_PATTERNS)
            if bid is not None and bid > 0:
                board_ids.append(bid)
            else:
                failures.append(f"无法识别单盘标识: '{ref}'（示例: 5号盘）")

        if raw.get("board_id"):
            bid = cls._extract_id(str(raw["board_id"]), cls._BOARD_PATTERNS)
            if bid and bid > 0 and bid not in board_ids:
                board_ids.append(bid)

        # 端口 ID
        port_ids: list[int] = []
        for ref in raw.get("port_refs", []):
            pid = cls._extract_id(str(ref), cls._PORT_PATTERNS)
            if pid is not None and pid > 0:
                port_ids.append(pid)
            else:
                failures.append(f"无法识别端口标识: '{ref}'（示例: 3口）")

        if raw.get("port_id"):
            pid = cls._extract_id(str(raw["port_id"]), cls._PORT_PATTERNS)
            if pid and pid > 0 and pid not in port_ids:
                port_ids.append(pid)

        # 构建 PortRef 列表（单盘-端口配对）
        port_ref_list: list[dict] = []
        if board_ids and port_ids:
            if len(board_ids) == len(port_ids):
                port_ref_list = [{"board_id": b, "port_id": p} for b, p in zip(board_ids, port_ids)]
            else:
                failures.append("单盘和端口数量不匹配")

        # 告警批量上限
        if len(port_ref_list) > ALARM_BATCH_MAX:
            failures.append(f"告警批量上限 {ALARM_BATCH_MAX}，当前 {len(port_ref_list)}")
            port_ref_list = port_ref_list[:ALARM_BATCH_MAX]

        # 颜色
        color: Optional[str] = None
        color_ref = raw.get("color_ref") or raw.get("color")
        if color_ref:
            color_str = str(color_ref).strip().lower()
            color = cls._COLOR_MAP.get(color_str, cls._COLOR_MAP.get(str(color_ref).strip()))
            if color is None:
                failures.append(f"无法识别颜色: '{color_ref}'（仅支持: 红/黄/绿）")

        # 时间解析
        start_time, end_time = cls._parse_time(raw.get("time_expression", "") or raw.get("time_range", ""))

        # 网元 ID
        ne_id = raw.get("ne_id")
        if ne_id is not None:
            try:
                ne_id = int(ne_id)
            except (ValueError, TypeError):
                ne_id = None

        return NormalizedParams(
            fiber_ids=fiber_ids,
            board_ids=board_ids,
            port_ids=port_ids,
            port_refs=port_ref_list,
            color=color,
            start_time=start_time,
            end_time=end_time,
            ne_id=ne_id,
            question=raw.get("question"),
            parse_failures=failures,
        )

    @classmethod
    def _extract_id(cls, text: str, patterns: list) -> Optional[int]:
        """使用模式列表从文本中提取整数 ID。

        【参数说明】
            text: 待提取的文本（如 "FIB-0012"）
            patterns: 正则模式列表，按优先级排列

        【返回值】
            提取的整数 ID，未匹配则返回 None
        """
        text = text.strip()
        for pattern, extractor in patterns:
            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return extractor(m)
                except (ValueError, IndexError):
                    continue
        return None

    @classmethod
    def _parse_time(cls, expr: str) -> tuple[Optional[str], Optional[str]]:
        """解析时间表达式为 ISO 8601 时间范围。

        【支持的格式】
        - "最近N天/周/月" → 相对时间范围
        - "X月X日到X日" → 绝对时间范围

        【返回值】
            (start_time, end_time) 的 ISO 8601 字符串元组，未识别则返回 (None, None)
        """
        if not expr:
            return (None, None)

        now = datetime.now()

        # "最近N天/周/月"
        m = re.search(r"最近\s*(\d+)\s*(天|日|周|星期|月)", expr)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            delta = {
                "天": timedelta(days=n),
                "日": timedelta(days=n),
                "周": timedelta(weeks=n),
                "星期": timedelta(weeks=n),
                "月": timedelta(days=n * 30),
            }[unit]
            return (
                (now - delta).strftime("%Y-%m-%dT00:00:00"),
                now.strftime("%Y-%m-%dT%H:%M:%S"),
            )

        # "X月X日到X日"
        m = re.search(r"(\d{1,2})月(\d{1,2})日?\s*(?:到|至|-|~)\s*(\d{1,2})日?", expr)
        if m:
            try:
                month, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
                start = datetime(now.year, month, d1)
                end = datetime(now.year, month, d2, 23, 59, 59)
                return (
                    start.strftime("%Y-%m-%dT%H:%M:%S"),
                    end.strftime("%Y-%m-%dT%H:%M:%S"),
                )
            except ValueError:
                pass

        return (None, None)


async def param_gate_node(state: MainGraphState) -> dict:
    """参数门禁节点：验证并归一化提取的参数。

    【输入】raw_extractions（来自规则引擎或 LLM 意图分类器的原始参数）
    【输出】normalized_params（NormalizedParams 序列化）
    【状态更新】normalized_params, raw_extractions
    """
    # 从规则匹配或意图结果中收集原始参数
    raw: dict = {}

    # 来自规则引擎匹配结果
    rule_match = state.get("rule_match")
    if rule_match and rule_match.get("params"):
        raw.update(rule_match["params"])

    # 来自 LLM 意图分类结果
    intent_result = state.get("intent_result")
    if intent_result:
        if intent_result.get("fiber_ids"):
            raw["fiber_refs"] = intent_result["fiber_ids"]
        if intent_result.get("board_ids"):
            raw["board_refs"] = intent_result["board_ids"]
        if intent_result.get("port_ids"):
            raw["port_refs"] = intent_result["port_ids"]
        if intent_result.get("color"):
            raw["color_ref"] = intent_result["color"]
        if intent_result.get("time_range"):
            raw["time_expression"] = intent_result["time_range"]
        if intent_result.get("ne_id"):
            raw["ne_id"] = intent_result["ne_id"]

    # 归一化
    normalized = ParamGate.validate_and_normalize(raw)

    # ---- 意图级必需参数检查 ----
    # 【功能说明】即使参数格式归一化成功，仍需检查当前意图的必需参数是否缺失。
    # 例如："查询光纤衰耗" 未指定光纤号 → fiber_ids 为空 → 应追问用户。
    intent = state.get("intent", "")
    if intent and normalized.parse_failures == []:
        required = _INTENT_REQUIRED_PARAMS.get(intent, [])
        for param_name in required:
            value = getattr(normalized, param_name, None)
            if not value:  # 空列表或 None
                friendly = _REQUIRED_PARAM_HINT.get(param_name, param_name)
                normalized.parse_failures.append(friendly)
                logger.info(f"[ParamGate] Required param missing: " f"intent={intent} missing={param_name}")

    if normalized.parse_failures:
        logger.warning(f"[ParamGate] Parse failures: {normalized.parse_failures}")

    return {
        "normalized_params": normalized.model_dump(),
        "raw_extractions": raw,
    }
