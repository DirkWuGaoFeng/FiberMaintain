"""
Degradation Manager — Five-level degradation chain [v7.1].

Levels:
  L0: Normal (14b full capability)
  L1: Simplified (7b takes over primary tasks)
  L2: Small model (3b minimal reasoning)
  L3: No LLM (pure template/rule-based responses)
  L4: Offline (serve cached/stale data only)

Features:
- Three-tier LLM probing (14b/7b/3b independently)
- 30s background probe coroutine
- Degradation/recovery events written to audit log
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ..config import (
    DEGRADATION_PROBE_INTERVAL,
    LLM_CONFIG,
    LLMTierConfig,
    OLLAMA_BASE_URL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)


class DegradationManager:
    """
    Five-level degradation manager with background health probing.

    Automatically detects LLM availability and adjusts degradation level.
    """

    def __init__(self):
        self.current_level: int = 0  # L0 = normal
        self._level_names = {
            0: "NORMAL (14b)",
            1: "SIMPLIFIED (7b)",
            2: "SMALL_MODEL (3b)",
            3: "NO_LLM (template)",
            4: "OFFLINE (cache)",
        }
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_probe_time: float = 0
        self._llm_status: dict[str, bool] = {
            "primary": True,   # 14b
            "secondary": True,  # 7b
            "tertiary": True,   # 3b
        }
        self._backend_available: bool = True

    @property
    def level_name(self) -> str:
        return self._level_names.get(self.current_level, "UNKNOWN")

    async def start(self) -> None:
        """Start background probing."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._probe_loop())
        logger.info("[Degradation] Manager started, probe interval: {DEGRADATION_PROBE_INTERVAL}s")

    async def stop(self) -> None:
        """Stop background probing."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _probe_loop(self) -> None:
        """Background probe loop (every 30s)."""
        while self._running:
            try:
                await self._probe_all()
                self._last_probe_time = time.time()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Degradation] Probe error: {e}")
            await asyncio.sleep(DEGRADATION_PROBE_INTERVAL)

    async def _probe_all(self) -> None:
        """Probe all components and update degradation level."""
        import httpx

        # Probe LLM tiers (each tier uses its own configured provider)
        async with httpx.AsyncClient(timeout=5.0) as client:
            self._llm_status["primary"] = await self._probe_model(client, LLM_CONFIG["primary"])
            self._llm_status["secondary"] = await self._probe_model(client, LLM_CONFIG["secondary"])
            self._llm_status["tertiary"] = await self._probe_model(client, LLM_CONFIG["tertiary"])

        # Probe backend
        try:
            from ..tools._http_client import fiber_http_client
            self._backend_available = await fiber_http_client.health_check()
        except Exception:
            self._backend_available = False

        # Calculate new level
        new_level = self._calculate_level()
        if new_level != self.current_level:
            old_level = self.current_level
            self.current_level = new_level
            direction = "降级" if new_level > old_level else "恢复"
            logger.warning(
                f"[Degradation] {direction}: L{old_level} → L{new_level} ({self.level_name})"
            )
            await self._log_degradation_event(old_level, new_level)

    async def _probe_model(self, client, cfg: LLMTierConfig) -> bool:
        """Probe a single tier model via its own provider."""
        try:
            if cfg.provider == "openai":
                # OpenAI 兼容协议：用最小请求验证模型可用性与鉴权
                resp = await client.post(
                    f"{OPENAI_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": cfg.model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                    timeout=30.0,
                )
            else:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={"model": cfg.model, "prompt": "hi", "stream": False},
                    timeout=30.0,
                )
            return resp.status_code == 200
        except Exception:
            return False

    def _calculate_level(self) -> int:
        """Calculate degradation level from probe results."""
        if not self._backend_available and not any(self._llm_status.values()):
            return 4  # L4: Offline

        if not self._llm_status["tertiary"]:
            if not self._backend_available:
                return 4  # L4: No LLM + no backend
            return 3  # L3: No LLM but backend available

        if not self._llm_status["secondary"]:
            return 2  # L2: Only 3b available

        if not self._llm_status["primary"]:
            return 1  # L1: 7b takes over

        return 0  # L0: All normal

    async def _log_degradation_event(self, old_level: int, new_level: int) -> None:
        """Write degradation event to audit log."""
        try:
            from ..observability.audit import write_audit_record
            await write_audit_record({
                "type": "degradation_change",
                "old_level": old_level,
                "new_level": new_level,
                "llm_status": self._llm_status.copy(),
                "backend_available": self._backend_available,
            })
        except ImportError:
            pass  # Audit module not loaded yet
        except Exception as e:
            logger.debug(f"[Degradation] Audit log failed: {e}")

    def get_status(self) -> dict:
        """Get current degradation status."""
        return {
            "level": self.current_level,
            "level_name": self.level_name,
            "llm_status": self._llm_status.copy(),
            "backend_available": self._backend_available,
            "last_probe": self._last_probe_time,
        }


# =============================================================================
# Singleton
# =============================================================================

_manager_instance: Optional[DegradationManager] = None


def get_degradation_manager() -> Optional[DegradationManager]:
    """Get the degradation manager singleton."""
    return _manager_instance


def create_degradation_manager() -> DegradationManager:
    """Create and register the degradation manager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = DegradationManager()
    return _manager_instance
