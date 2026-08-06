"""
LLM 调用级审计记录器。

每次 LLM 调用记录: trace_id, node, model, input, output, tokens, latency, prompt_version。
支持按 trace_id 查询完整调用链。
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 内存中保留最近 500 条 LLM 调用记录
_call_history: deque["LLMAuditRecord"] = deque(maxlen=500)


@dataclass
class LLMAuditRecord:
    """单次 LLM 调用的完整审计记录。"""

    trace_id: str
    node: str  # 调用节点名
    model: str
    input_messages: list[str]
    output: str
    tokens_input: int
    tokens_output: int
    latency_ms: int
    prompt_version: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "node": self.node,
            "model": self.model,
            "input_preview": str(self.input_messages)[:500],
            "output_preview": self.output[:300],
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_total": self.tokens_total,
            "latency_ms": self.latency_ms,
            "prompt_version": self.prompt_version,
        }


def record_llm_call(record: LLMAuditRecord) -> None:
    """记录一次 LLM 调用。"""
    _call_history.append(record)
    logger.debug(
        f"[LLMAudit] {record.node} | {record.model} | "
        f"{record.tokens_total} tokens | {record.latency_ms}ms"
    )


def get_call_history(trace_id: Optional[str] = None) -> list[LLMAuditRecord]:
    """查询 LLM 调用历史。指定 trace_id 则过滤。"""
    if trace_id:
        return [r for r in _call_history if r.trace_id == trace_id]
    return list(_call_history)


def get_total_tokens(trace_id: str) -> int:
    """获取某请求的总 token 消耗。"""
    return sum(r.tokens_total for r in _call_history if r.trace_id == trace_id)
