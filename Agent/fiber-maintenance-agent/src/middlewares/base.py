"""Middleware 基类与执行链。"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any

@dataclass
class RunContext:
    session_id: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    messages: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # 领域校验告警
    knowledge_snippets: list[dict] = field(default_factory=list)
    offline: bool = False
    meta: dict = field(default_factory=dict)

class Middleware:
    async def before_model(self, ctx: RunContext) -> None: ...
    async def after_model(self, ctx: RunContext, response: Any) -> None: ...
    async def before_tool(self, ctx: RunContext, tool_name: str,
                          args: dict) -> None: ...
    async def after_tool(self, ctx: RunContext, tool_name: str,
                         args: dict, result: Any) -> None: ...
    async def on_timeout(self, ctx: RunContext) -> None: ...

class MiddlewareChain:
    def __init__(self, mws: list[Middleware]):
        self.mws = mws

    async def before_model(self, ctx: RunContext) -> None:
        for mw in self.mws:
            await mw.before_model(ctx)

    async def after_model(self, ctx: RunContext, resp: Any) -> None:
        for mw in self.mws:
            await mw.after_model(ctx, resp)

    async def before_tool(self, ctx: RunContext, name: str, args: dict) -> None:
        for mw in self.mws:
            await mw.before_tool(ctx, name, args)

    async def after_tool(self, ctx: RunContext, name: str,
                         args: dict, result: Any) -> None:
        for mw in self.mws:
            await mw.after_tool(ctx, name, args, result)

    async def on_timeout(self, ctx: RunContext) -> None:
        for mw in self.mws:
            await mw.on_timeout(ctx)