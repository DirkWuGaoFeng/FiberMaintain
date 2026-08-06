"""
Internal tools: system diagnostics, event query, cache inspection [v7.1].

These tools provide observability into the Agent's own state.
They do NOT call the C++ backend — they inspect local state.

Tools:
  - event_query: query recent events from asyncio.Queue
  - cache_query: inspect LocalCache entries
  - audit_query: query audit trail records
  - system_health: overall system health check
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
# Input Schemas
# =============================================================================

class EventQueryInput(BaseModel):
    event_type: Optional[str] = Field(
        default=None, description="Filter: alarm / fiber_color / fiber_stats"
    )
    limit: int = Field(default=10, description="Max events to return (1-50)")


class CacheQueryInput(BaseModel):
    key_pattern: Optional[str] = Field(default=None, description="Cache key pattern to search")


class AuditQueryInput(BaseModel):
    request_id: Optional[str] = Field(default=None, description="Specific request ID")
    limit: int = Field(default=10, description="Max records (1-50)")


class SystemHealthInput(BaseModel):
    pass  # No parameters


# =============================================================================
# Internal Tools
# =============================================================================

@tool(args_schema=EventQueryInput)
async def event_query(event_type: Optional[str] = None, limit: int = 10) -> str:
    """Query recent system events (alarms, color changes, stats updates).
    Returns: JSON with events array."""
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
    """Inspect local cache entries (TTL, staleness, hit rate).
    Returns: JSON with cache stats and matching entries."""
    try:
        from ..cache.local_cache import get_local_cache

        cache = get_local_cache()
        if cache is None:
            return json.dumps({"entries": [], "note": "缓存未初始化"})

        stats = await cache.get_stats()
        entries = await cache.query_keys(pattern=key_pattern) if key_pattern else []
        return json.dumps({
            "stats": stats,
            "matching_entries": entries[:20],
        }, ensure_ascii=False)
    except ImportError:
        return json.dumps({"entries": [], "note": "缓存模块未加载"})
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool(args_schema=AuditQueryInput)
async def audit_query(request_id: Optional[str] = None, limit: int = 10) -> str:
    """Query audit trail records (request processing history).
    Returns: JSON with audit records."""
    limit = max(1, min(limit, 50))

    try:
        from ..config import AUDIT_LOG_PATH
        from pathlib import Path

        audit_path = Path(AUDIT_LOG_PATH)
        if not audit_path.exists():
            return json.dumps({"records": [], "note": "审计日志文件不存在"})

        records = []
        with open(audit_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Read from end (most recent)
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
    """Check overall system health (Ollama, backend, cache, degradation level).
    Returns: JSON with component health status."""
    health = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "components": {},
    }

    # Check Ollama
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            health["components"]["ollama"] = "healthy" if resp.status_code == 200 else "degraded"
    except Exception:
        health["components"]["ollama"] = "unavailable"

    # Check C++ backend
    try:
        from ._http_client import fiber_http_client
        backend_ok = await fiber_http_client.health_check()
        health["components"]["backend"] = "healthy" if backend_ok else "unavailable"
    except Exception:
        health["components"]["backend"] = "unavailable"

    # Check degradation level
    try:
        from ..resilience.degradation import get_degradation_manager
        dm = get_degradation_manager()
        health["components"]["degradation_level"] = dm.current_level if dm else 0
    except ImportError:
        health["components"]["degradation_level"] = "module_not_loaded"

    # Circuit breaker state
    try:
        from ._http_client import fiber_http_client
        health["components"]["circuit_breaker"] = fiber_http_client.circuit_breaker.state.value
    except Exception:
        health["components"]["circuit_breaker"] = "unknown"

    return json.dumps(health, ensure_ascii=False)
