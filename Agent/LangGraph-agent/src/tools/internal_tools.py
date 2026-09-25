"""
内部工具集 —— 系统诊断、事件查询、缓存检查 [v7.1]。

这些工具提供对 Agent 自身状态的可观测性。
它们不调用 C++ 后端——而是检查本地状态。

工具：
  - event_query：从 asyncio.Queue 查询最近事件
  - cache_query：检查 LocalCache 条目
  - audit_query：查询审计轨迹记录
  - system_health：整体系统健康检查
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# 输入参数契约（Input Schemas）
# =============================================================================


class EventQueryInput(BaseModel):
    event_type: Optional[str] = Field(default=None, description="Filter: alarm / fiber_color / fiber_stats")
    limit: int = Field(default=10, description="Max events to return (1-50)")


class CacheQueryInput(BaseModel):
    key_pattern: Optional[str] = Field(default=None, description="Cache key pattern to search")


class AuditQueryInput(BaseModel):
    request_id: Optional[str] = Field(default=None, description="Specific request ID")
    limit: int = Field(default=10, description="Max records (1-50)")


class SystemHealthInput(BaseModel):
    pass  # 无需参数


# =============================================================================
# 内部工具（Internal Tools）
# =============================================================================


@tool(args_schema=EventQueryInput)
async def event_query(event_type: Optional[str] = None, limit: int = 10) -> str:
    """查询最近系统事件（告警、颜色变化、统计更新）。
    返回：JSON，含事件数组。"""
    limit = max(1, min(limit, 50))

    try:
        from ..events.listener import get_event_listener

        listener = get_event_listener()
        if listener is None:
            return json.dumps({"events": [], "note": "事件监听器未启动"})

        events = listener.get_recent_events(limit=limit, event_type=event_type)
        return json.dumps({"events": events, "count": len(events)}, ensure_ascii=False)
    except ImportError:
        return json.dumps({"events": [], "note": "事件模块未加载"})
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool(args_schema=CacheQueryInput)
async def cache_query(key_pattern: Optional[str] = None) -> str:
    """检查本地缓存条目（TTL、过期情况、命中率）。
    返回：JSON，含缓存统计与匹配条目。"""
    try:
        from ..cache.local_cache import get_local_cache

        cache = get_local_cache()
        if cache is None:
            return json.dumps({"entries": [], "note": "缓存未初始化"})

        stats = await cache.get_stats()
        entries = await cache.query_keys(pattern=key_pattern) if key_pattern else []
        return json.dumps(
            {
                "stats": stats,
                "matching_entries": entries[:20],
            },
            ensure_ascii=False,
        )
    except ImportError:
        return json.dumps({"entries": [], "note": "缓存模块未加载"})
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool(args_schema=AuditQueryInput)
async def audit_query(request_id: Optional[str] = None, limit: int = 10) -> str:
    """查询审计轨迹记录（请求处理历史）。
    返回：JSON，含审计记录。"""
    limit = max(1, min(limit, 50))

    try:
        from pathlib import Path

        from ..config import AUDIT_LOG_PATH

        audit_path = Path(AUDIT_LOG_PATH)
        if not audit_path.exists():
            return json.dumps({"records": [], "note": "审计日志文件不存在"})

        records = []
        with open(audit_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 从文件末尾（最近）开始读取
        for line in reversed(lines[-100:]):
            try:
                record = json.loads(line.strip())
                if request_id and record.get("request_id") != request_id:
                    continue
                records.append(record)
                if len(records) >= limit:
                    break
            except json.JSONDecodeError:
                continue

        return json.dumps({"records": records, "count": len(records)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool(args_schema=SystemHealthInput)
async def system_health() -> str:
    """检查整体系统健康（Ollama、后端、缓存、降级等级）。
    返回：JSON，含各组件健康状态。"""
    health = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "components": {},
    }

    # 检查 Ollama
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            health["components"]["ollama"] = "healthy" if resp.status_code == 200 else "degraded"
    except Exception:
        health["components"]["ollama"] = "unavailable"

    # 检查 C++ 后端
    try:
        from ._http_client import fiber_http_client

        backend_ok = await fiber_http_client.health_check()
        health["components"]["backend"] = "healthy" if backend_ok else "unavailable"
    except Exception:
        health["components"]["backend"] = "unavailable"

    # 检查降级等级
    try:
        from ..resilience.degradation import get_degradation_manager

        dm = get_degradation_manager()
        health["components"]["degradation_level"] = dm.current_level if dm else 0
    except ImportError:
        health["components"]["degradation_level"] = "module_not_loaded"

    # 熔断器状态
    try:
        from ._http_client import fiber_http_client

        health["components"]["circuit_breaker"] = fiber_http_client.circuit_breaker.state.value
    except Exception:
        health["components"]["circuit_breaker"] = "unknown"

    return json.dumps(health, ensure_ascii=False)
