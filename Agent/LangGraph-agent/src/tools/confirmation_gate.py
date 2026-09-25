"""
写操作确认门控 [改进清单 P1-B]。

针对真实写操作（pull_call_create / pull_call_cancel）的轻量级 HITL（人在回路）机制。设计：

- 没有有效的确认令牌，工具绝不执行写操作。
- 首次调用将请求登记为待确认动作并返回令牌；前端渲染确认卡片（ClarifyCard 模式）。
- 用户确认后弹出待确认动作并执行。
- 待确认动作会过期（CONFIRM_TTL_SECONDS）并设有上限，避免话痨的 LLM 积累无界写意图。

风险评估：只读工具不加门控；写工具必须通过门控。
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONFIRM_TTL_SECONDS = 600  # 确认有效期 10 分钟
MAX_PENDING = 50


class ConfirmationGate:
    """等待用户确认的待执行写操作的内存注册表。"""

    def __init__(self, ttl_seconds: int = CONFIRM_TTL_SECONDS, max_pending: int = MAX_PENDING):
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def request(self, operation: str, params: dict, description: str) -> Optional[dict]:
        """注册一个写意图。返回待确认条目；队列已满时返回 None。"""
        with self._lock:
            self._evict_expired_locked()
            if len(self._pending) >= self._max_pending:
                logger.warning("[ConfirmGate] Pending queue full, rejecting new intent")
                return None
            token = secrets.token_hex(8)
            entry = {
                "token": token,
                "operation": operation,
                "params": params,
                "description": description,
                "created_at": time.time(),
            }
            self._pending[token] = entry
            logger.info(f"[ConfirmGate] Pending write registered: {operation} ({token})")
            return entry

    def confirm(self, token: str) -> Optional[dict]:
        """消费一个待确认条目。每条只返回一次；未知或已过期时返回 None。"""
        with self._lock:
            entry = self._pending.pop(token, None)
        if entry is None:
            return None
        if time.time() - entry["created_at"] >= self._ttl:
            logger.info(f"[ConfirmGate] Token expired: {token}")
            return None
        return entry

    def list_pending(self) -> list[dict]:
        """返回未过期的待确认条目（供前端确认面板使用）。"""
        with self._lock:
            self._evict_expired_locked()
            return [
                {
                    "token": e["token"],
                    "operation": e["operation"],
                    "params": e["params"],
                    "description": e["description"],
                }
                for e in self._pending.values()
            ]

    def _evict_expired_locked(self) -> None:
        now = time.time()
        expired = [t for t, e in self._pending.items() if now - e["created_at"] >= self._ttl]
        for t in expired:
            del self._pending[t]


_gate: Optional[ConfirmationGate] = None


def get_confirmation_gate() -> ConfirmationGate:
    """进程级单例确认门控。"""
    global _gate
    if _gate is None:
        _gate = ConfirmationGate()
    return _gate
