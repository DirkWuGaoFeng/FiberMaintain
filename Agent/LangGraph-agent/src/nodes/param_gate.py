"""
Parameter Gate Node — Layer 2 validation and normalization.

Converts raw user expressions to backend-compatible strong types:
- "FIB-0012" → 12, "13号光纤" → 13, "5号盘" → 5
- Color mapping: "红色" → "RED"
- Time parsing: "最近一周" → ISO 8601 range

Pure programmatic, zero LLM calls, latency < 5ms.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from ..config import ALARM_BATCH_MAX, BATCH_MAX_TOTAL
from ..graph.state import MainGraphState, NormalizedParams

logger = logging.getLogger(__name__)


class ParamGate:
    """
    Parameter validation gate: converts raw expressions to precise backend types.

    Three-layer defense Layer 2:
    ① Format conversion (regex patterns)
    ② Business rules (fiber_id > 0, len ≤ 200)
    ③ Enum validation (color ∈ {RED, YELLOW, GREEN})
    """

    # ===== Format conversion patterns =====
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
        "红色": "RED", "红": "RED", "red": "RED",
        "黄色": "YELLOW", "黄": "YELLOW", "yellow": "YELLOW",
        "绿色": "GREEN", "绿": "GREEN", "green": "GREEN",
    }

    @classmethod
    def validate_and_normalize(cls, raw: dict) -> NormalizedParams:
        """
        Layer 2: Validate and normalize raw parameters.

        Returns:
            NormalizedParams (strong-typed, aligned with backend int32/enum)
        """
        failures: list[str] = []

        # Fiber IDs
        fiber_ids: list[int] = []
        for ref in raw.get("fiber_refs", []):
            fid = cls._extract_id(str(ref), cls._FIBER_PATTERNS)
            if fid is not None and fid > 0:
                fiber_ids.append(fid)
            else:
                failures.append(f"无法识别光纤标识: '{ref}'（示例: FIB-0012 或 12号光纤）")

        # Also handle direct fiber_id param
        if raw.get("fiber_id"):
            fid = cls._extract_id(str(raw["fiber_id"]), cls._FIBER_PATTERNS)
            if fid and fid > 0 and fid not in fiber_ids:
                fiber_ids.append(fid)

        # Batch limit
        if len(fiber_ids) > BATCH_MAX_TOTAL:
            failures.append(f"批量上限 {BATCH_MAX_TOTAL} 条，当前 {len(fiber_ids)} 条")
            fiber_ids = fiber_ids[:BATCH_MAX_TOTAL]

        # Board IDs
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

        # Port IDs
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

        # Build PortRef list
        port_ref_list: list[dict] = []
        if board_ids and port_ids:
            if len(board_ids) == len(port_ids):
                port_ref_list = [
                    {"board_id": b, "port_id": p} for b, p in zip(board_ids, port_ids)
                ]
            else:
                failures.append("单盘和端口数量不匹配")

        # Alarm batch limit
        if len(port_ref_list) > ALARM_BATCH_MAX:
            failures.append(f"告警批量上限 {ALARM_BATCH_MAX}，当前 {len(port_ref_list)}")
            port_ref_list = port_ref_list[:ALARM_BATCH_MAX]

        # Color
        color: Optional[str] = None
        color_ref = raw.get("color_ref") or raw.get("color")
        if color_ref:
            color_str = str(color_ref).strip().lower()
            color = cls._COLOR_MAP.get(color_str, cls._COLOR_MAP.get(str(color_ref).strip()))
            if color is None:
                failures.append(f"无法识别颜色: '{color_ref}'（仅支持: 红/黄/绿）")

        # Time parsing
        start_time, end_time = cls._parse_time(raw.get("time_expression", "") or raw.get("time_range", ""))

        # NE ID
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
        """Extract integer ID from text using pattern list."""
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
        """Parse time expression to ISO 8601 range."""
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
    """
    Parameter gate node: validate and normalize extracted parameters.

    Input: raw_extractions from rule engine or LLM intent classifier
    Output: normalized_params (NormalizedParams serialized)
    """
    # Gather raw parameters from rule match or intent result
    raw: dict = {}

    # From rule engine match
    rule_match = state.get("rule_match")
    if rule_match and rule_match.get("params"):
        raw.update(rule_match["params"])

    # From LLM intent result
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

    # Normalize
    normalized = ParamGate.validate_and_normalize(raw)

    if normalized.parse_failures:
        logger.warning(f"[ParamGate] Parse failures: {normalized.parse_failures}")

    return {
        "normalized_params": normalized.model_dump(),
        "raw_extractions": raw,
    }
