"""
审计日志 [v7.1]。

本地 JSON Lines 审计日志（data/audit.jsonl）。
记录字段：request_id、user_input、processing_path、api_calls、output、latency_ms、degradation_level。
保留期限：180 天（可通过 AUDIT_RETENTION_DAYS 配置）。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import AUDIT_LOG_PATH, AUDIT_RETENTION_DAYS

logger = logging.getLogger(__name__)


async def write_audit_record(record: dict) -> None:
    """
    将单条审计记录写入 JSONL 文件。

    Args:
        record: 包含审计字段的字典。常见字段：
            - request_id: str
            - user_input: str
            - processing_path: str (fast/normal/heavy/degraded/blocked)
            - api_calls: list[str]
            - output: str（已截断）
            - latency_ms: int
            - degradation_level: int
            - type: str（可选，用于系统事件）
    """
    try:
        record.setdefault("timestamp", datetime.now().isoformat())
        record.setdefault("epoch", time.time())

        path = Path(AUDIT_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    except Exception as e:
        logger.debug(f"[Audit] Write failed: {e}")


async def write_request_audit(
    request_id: str,
    user_input: str,
    processing_path: str,
    output: str,
    latency_ms: int,
    degradation_level: int = 0,
    api_calls: Optional[list[str]] = None,
    rule_match: Optional[str] = None,
    loop_count: int = 0,
) -> None:
    """
    写入一条标准的请求审计记录。

    这是每次请求结束时调用的主要审计函数。
    """
    await write_audit_record(
        {
            "type": "request",
            "request_id": request_id,
            "user_input": user_input[:200],  # 出于隐私考虑进行截断
            "processing_path": processing_path,
            "output": output[:300] if output else "",
            "latency_ms": latency_ms,
            "degradation_level": degradation_level,
            "api_calls": api_calls or [],
            "rule_match": rule_match,
            "loop_count": loop_count,
        }
    )


async def cleanup_old_records() -> int:
    """
    移除早于 AUDIT_RETENTION_DAYS 的审计记录。

    Returns:
        被移除的行数。
    """
    path = Path(AUDIT_LOG_PATH)
    if not path.exists():
        return 0

    cutoff = time.time() - (AUDIT_RETENTION_DAYS * 86400)
    kept_lines = []
    removed = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if record.get("epoch", time.time()) >= cutoff:
                        kept_lines.append(line)
                    else:
                        removed += 1
                except json.JSONDecodeError:
                    removed += 1

        if removed > 0:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)
            logger.info(f"[Audit] Cleaned up {removed} old records")

    except Exception as e:
        logger.error(f"[Audit] Cleanup failed: {e}")

    return removed
