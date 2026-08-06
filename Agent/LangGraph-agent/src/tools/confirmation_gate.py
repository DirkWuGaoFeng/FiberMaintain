"""
Write-operation confirmation gate [改进清单 P1-B].

Lightweight HITL for real write operations (pull_call_create /
pull_call_cancel). Design:

- Tools never write without a valid confirmation token.
- First invocation stores the request as a pending action and returns a
  token; the frontend renders a confirm card (ClarifyCard pattern).
- User confirmation pops the pending action and executes it.
- Pending actions expire (CONFIRM_TTL_SECONDS) and are capped, so a
  chatty LLM cannot accumulate unbounded write intents.

Risk grading: read-only tools carry no gate; write tools are gated.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONFIRM_TTL_SECONDS = 600  # 10 minutes to confirm
MAX_PENDING = 50


class ConfirmationGate:
    """In-memory registry of pending write operations awaiting user consent."""

    def __init__(self, ttl_seconds: int = CONFIRM_TTL_SECONDS, max_pending: int = MAX_PENDING):
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def request(
        self, operation: str, params: dict, description: str
    ) -> Optional[dict]:
        """Register a write intent. Returns the pending entry or None when full."""
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
        """Consume a pending entry. Returns it once, or None when unknown/expired."""
        with self._lock:
            entry = self._pending.pop(token, None)
        if entry is None:
            return None
        if time.time() - entry["created_at"] >= self._ttl:
            logger.info(f"[ConfirmGate] Token expired: {token}")
            return None
        return entry

    def list_pending(self) -> list[dict]:
        """Non-expired pending entries (for the frontend confirm panel)."""
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
    """Process-wide singleton confirmation gate."""
    global _gate
    if _gate is None:
        _gate = ConfirmationGate()
    return _gate
