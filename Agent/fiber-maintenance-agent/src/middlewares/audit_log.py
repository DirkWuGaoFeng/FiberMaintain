"""AuditLogMiddleware：工具调用全链路审计（JSONL，§5.4）。"""
from __future__ import annotations
import time, json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .base import Middleware, RunContext
from src.settings import settings

class AuditLogMiddleware(Middleware):
    def __init__(self) -> None:
        path = Path(settings.app["log_dir"]) / "audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._t0: dict[str, float] = {}

    def _write(self, record: dict) -> None:
        record["timestamp"] = datetime.now(timezone.utc).astimezone().isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def before_tool(self, ctx: RunContext, tool_name: str,
                          args: dict) -> None:
        self._t0[tool_name] = time.perf_counter()
        self._write({"event": "tool_call_start", "trace_id": ctx.trace_id,
                     "session_id": ctx.session_id,
                     "tool": tool_name, "args": args})

    async def after_tool(self, ctx: RunContext, tool_name: str,
                         args: dict, result: Any) -> None:
        elapsed = (time.perf_counter() - self._t0.pop(tool_name,
                                                      time.perf_counter())) * 1000
        self._write({"event": "tool_call_end", "trace_id": ctx.trace_id,
                     "session_id": ctx.session_id,
                     "tool": tool_name, "args": args, "status": "ok",
                     "elapsed_ms": round(elapsed, 2)})

    async def on_timeout(self, ctx: RunContext) -> None:
        self._write({"event": "timeout", "trace_id": ctx.trace_id,
                     "session_id": ctx.session_id, "meta": ctx.meta})