"""
降级管理器 — 五级降级链路 [v7.1]。

级别：
  L0：正常（14b 完整能力）
  L1：简化（7b 接管主要任务）
  L2：小模型（3b 最小推理）
  L3：无 LLM（纯模板/规则应答）
  L4：离线（仅提供缓存/旧数据）

特性：
- 三层 LLM 探测（14b/7b/3b 独立）
- 30s 后台探测协程
- 降级/恢复事件写入审计日志
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ..config import (
    DEGRADATION_PROBE_INTERVAL,
    LLM_CONFIG,
    OLLAMA_BASE_URL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    LLMTierConfig,
)

logger = logging.getLogger(__name__)


class DegradationManager:
    """
    带后台健康探测的五级降级管理器。

    自动检测 LLM 可用性并调整降级级别。
    """

    def __init__(self):
        self.current_level: int = 0  # L0 = 正常
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
            "primary": True,  # 14b
            "secondary": True,  # 7b
            "tertiary": True,  # 3b
        }
        self._backend_available: bool = True

    @property
    def level_name(self) -> str:
        return self._level_names.get(self.current_level, "UNKNOWN")

    async def start(self) -> None:
        """启动后台探测。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._probe_loop())
        logger.info("[Degradation] Manager started, probe interval: {DEGRADATION_PROBE_INTERVAL}s")

    async def stop(self) -> None:
        """停止后台探测。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _probe_loop(self) -> None:
        """后台探测循环（每 30 秒）。"""
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
        """探测所有组件并更新降级级别。"""
        import httpx

        # 探测各 LLM 层级（每个层级使用各自配置的提供商）
        async with httpx.AsyncClient(timeout=5.0) as client:
            self._llm_status["primary"] = await self._probe_model(client, LLM_CONFIG["primary"])
            self._llm_status["secondary"] = await self._probe_model(client, LLM_CONFIG["secondary"])
            self._llm_status["tertiary"] = await self._probe_model(client, LLM_CONFIG["tertiary"])

        # 探测后端
        try:
            from ..tools._http_client import fiber_http_client

            self._backend_available = await fiber_http_client.health_check()
        except Exception:
            self._backend_available = False

        # 计算新级别
        new_level = self._calculate_level()
        if new_level != self.current_level:
            old_level = self.current_level
            self.current_level = new_level
            direction = "降级" if new_level > old_level else "恢复"
            logger.warning(f"[Degradation] {direction}: L{old_level} → L{new_level} ({self.level_name})")
            await self._log_degradation_event(old_level, new_level)

    async def _probe_model(self, client, cfg: LLMTierConfig) -> bool:
        """通过各自提供商探测单个层级模型。"""
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
        """根据探测结果计算降级级别。"""
        if not self._backend_available and not any(self._llm_status.values()):
            return 4  # L4：离线

        if not self._llm_status["tertiary"]:
            if not self._backend_available:
                return 4  # L4：无 LLM 且无后端
            return 3  # L3：无 LLM 但后端可用

        if not self._llm_status["secondary"]:
            return 2  # L2：仅有 3b 可用

        if not self._llm_status["primary"]:
            return 1  # L1：7b 接管

        return 0  # L0：全部正常

    async def _log_degradation_event(self, old_level: int, new_level: int) -> None:
        """将降级事件写入审计日志。"""
        try:
            from ..observability.audit import write_audit_record

            await write_audit_record(
                {
                    "type": "degradation_change",
                    "old_level": old_level,
                    "new_level": new_level,
                    "llm_status": self._llm_status.copy(),
                    "backend_available": self._backend_available,
                }
            )
        except ImportError:
            pass  # 审计模块尚未加载
        except Exception as e:
            logger.debug(f"[Degradation] Audit log failed: {e}")

    def get_status(self) -> dict:
        """获取当前降级状态。"""
        return {
            "level": self.current_level,
            "level_name": self.level_name,
            "llm_status": self._llm_status.copy(),
            "backend_available": self._backend_available,
            "last_probe": self._last_probe_time,
        }


# =============================================================================
# Singleton（单例）
# =============================================================================

_manager_instance: Optional[DegradationManager] = None


def get_degradation_manager() -> Optional[DegradationManager]:
    """获取降级管理器单例。"""
    return _manager_instance


def create_degradation_manager() -> DegradationManager:
    """创建并注册降级管理器单例。"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = DegradationManager()
    return _manager_instance
