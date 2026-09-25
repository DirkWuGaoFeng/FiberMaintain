"""
健康探测 [v7.1]。

提供以下组件的健康检查：
- LLM 服务（本地 Ollama，或 OpenAI 兼容 API，如百炼）
- C++ 后端（API 网关）
- ChromaDB（向量库，可选）

被以下模块使用：
- server.py 中的 /health 端点
- DegradationManager
- internal_tools.system_health
"""

from __future__ import annotations

import logging
import time

import httpx

from ..config import (
    CHROMADB_HOST,
    CHROMADB_PORT,
    LLM_CONFIG,
    OLLAMA_BASE_URL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)


class HealthProbe:
    """多组件健康探测器。"""

    def __init__(self):
        self._last_check: dict[str, dict] = {}

    async def check_all(self) -> dict:
        """
        检查所有组件并返回健康状态。

        Returns:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "components": {...},
                "timestamp": str,
            }
        """
        components = {}

        # LLM 服务（Ollama 或 OpenAI 兼容 API）
        components["llm"] = await self._check_llm_service()

        # 后端
        components["backend"] = await self._check_backend()

        # ChromaDB（可选）
        components["chromadb"] = await self._check_chromadb()

        # 确定整体状态
        statuses = [c["status"] for c in components.values()]
        if all(s == "healthy" for s in statuses):
            overall = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"

        result = {
            "status": overall,
            "components": components,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        self._last_check = result
        return result

    async def _check_llm_service(self) -> dict:
        """检查各层级实际使用的每个 LLM 提供商的健康状态。"""
        providers = {cfg.provider for cfg in LLM_CONFIG.values()}
        per_provider: dict[str, dict] = {}
        if "openai" in providers:
            per_provider["openai"] = await self._check_openai()
        if "ollama" in providers:
            per_provider["ollama"] = await self._check_ollama()

        statuses = [c["status"] for c in per_provider.values()]
        if all(s == "healthy" for s in statuses):
            overall = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"
        return {"status": overall, "providers": per_provider}

    async def _check_openai(self) -> dict:
        """检查 OpenAI 兼容 API 的健康状态（例如百炼 DashScope）。"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{OPENAI_API_BASE}/models",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                )
                if resp.status_code == 200:
                    models = resp.json().get("data", [])
                    return {
                        "status": "healthy",
                        "provider": "openai-compatible",
                        "models_loaded": len(models),
                        "url": OPENAI_API_BASE,
                    }
                # 401/403 表示端点可达但鉴权失败
                if resp.status_code in (401, 403):
                    return {
                        "status": "degraded",
                        "http_code": resp.status_code,
                        "note": "API key invalid or unauthorized",
                    }
                return {"status": "degraded", "http_code": resp.status_code}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def _check_ollama(self) -> dict:
        """检查 Ollama 服务的健康状态。"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {
                        "status": "healthy",
                        "models_loaded": len(models),
                        "url": OLLAMA_BASE_URL,
                    }
                return {"status": "degraded", "http_code": resp.status_code}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def _check_backend(self) -> dict:
        """检查 C++ 后端的健康状态。"""
        try:
            from ..tools._http_client import fiber_http_client

            ok = await fiber_http_client.health_check()
            circuit_state = fiber_http_client.circuit_breaker.state.value
            return {
                "status": "healthy" if ok else "unhealthy",
                "circuit_breaker": circuit_state,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def _check_chromadb(self) -> dict:
        """检查 ChromaDB 的健康状态（可选组件）。"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"http://{CHROMADB_HOST}:{CHROMADB_PORT}/api/v1/heartbeat")
                if resp.status_code == 200:
                    return {"status": "healthy"}
                return {"status": "degraded", "http_code": resp.status_code}
        except Exception:
            # ChromaDB 为可选组件 — 不标记为 unhealthy
            return {"status": "degraded", "note": "ChromaDB not reachable (optional)"}

    @property
    def last_result(self) -> dict:
        """获取上一次健康检查结果。"""
        return self._last_check


# 模块级实例
health_probe = HealthProbe()
