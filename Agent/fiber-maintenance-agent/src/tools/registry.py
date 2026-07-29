"""Tool 注册器：装饰器自动构建 OpenAI function schema。"""
from __future__ import annotations
import asyncio, inspect, logging, typing, time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from src.monitoring.metrics import TOOL_CALLS, TOOL_ERRORS

logger = logging.getLogger("fiber.tool")

_TYPE_MAP = {
    int: "integer", float: "number", str: "string", bool: "boolean",
}

@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    schema: dict
    tags: list[str] = field(default_factory=list)
    plugin: str | None = None          # 来源插件名（None=内置）

    def openai_schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.schema,
        }}

    async def ainvoke(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        logger.info("[Tool] 调用 %s args=%s", self.name,
                    {k: (str(v)[:100] if not isinstance(v, str) else v[:100]) for k, v in kwargs.items()})
        try:
            result = self.fn(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            elapsed_ms = (time.perf_counter() - started) * 1000
            result_preview = str(result)[:200] if result else "None"
            logger.info("[Tool] %s 完成 result_len=%d elapsed=%.0fms preview=%.200s",
                        self.name, len(str(result)), elapsed_ms, result_preview)
            TOOL_CALLS.labels(tool=self.name, status="ok").inc()
            return result
        except Exception as e:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.error("[Tool] %s 异常 elapsed=%.0fms error=%s",
                         self.name, elapsed_ms, e, exc_info=True)
            TOOL_CALLS.labels(tool=self.name, status="error").inc()
            TOOL_ERRORS.labels(tool=self.name).inc()
            raise
        finally:
            pass  # 延迟已在上方记录


_REGISTRY: dict[str, Tool] = {}

def _build_schema(fn: Callable) -> dict:
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for pname, param in sig.parameters.items():
        if pname in ("self", "ctx"):
            continue
        ptype = hints.get(pname, str)
        origin = typing.get_origin(ptype)
        if origin in (list, typing.List):
            inner = typing.get_args(ptype)[0]
            js = {"type": "array",
                  "items": {"type": _TYPE_MAP.get(inner, "string")}}
        elif origin is typing.Union:   # Optional
            args = [a for a in typing.get_args(ptype) if a is not type(None)]
            js = {"type": _TYPE_MAP.get(args[0], "string")} if args else {"type": "string"}
        else:
            js = {"type": _TYPE_MAP.get(ptype, "string")}
        # 从 docstring Args 段提取参数说明
        desc = _arg_doc(fn, pname)
        if desc:
            js["description"] = desc
        props[pname] = js
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}

def _arg_doc(fn: Callable, pname: str) -> str:
    doc = fn.__doc__ or ""
    for line in doc.splitlines():
        line = line.strip()
        if line.startswith(f"{pname}:") or line.startswith(f"{pname} ("):
            return line.split(":", 1)[1].strip() if ":" in line else ""
    return ""

def tool(name: str | None = None, description: str | None = None,
         tags: list[str] | None = None):
    """Tool 装饰器。description 缺省取 docstring 首行。"""
    def deco(fn: Callable) -> Callable:
        tname = name or fn.__name__
        doc = (fn.__doc__ or "").strip()
        tdesc = description or (doc.splitlines()[0] if doc else tname)
        t = Tool(name=tname, description=tdesc, fn=fn,
                 schema=_build_schema(fn), tags=tags or [])
        _REGISTRY[tname] = t
        return fn
    return deco

def register_tool_object(t: Tool) -> None:
    """插件注册入口。"""
    _REGISTRY[t.name] = t

def unregister_tool(name: str) -> None:
    _REGISTRY.pop(name, None)

def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)

def list_tools() -> list[Tool]:
    return list(_REGISTRY.values())

def tool_schemas(names: list[str]) -> list[dict]:
    return [_REGISTRY[n].openai_schema() for n in names if n in _REGISTRY]

async def execute_tool(name: str, args: dict) -> Any:
    t = _REGISTRY.get(name)
    if t is None:
        logger.error("[Tool] 未注册的工具: %s", name)
        raise KeyError(f"未注册的工具: {name}")
    return await asyncio.wait_for(t.ainvoke(**args), timeout=30)