"""插件化框架：目录自动发现 + 热加载（§15）。
- Tool 插件：plugins/tools/*.py，继承 ToolPlugin
- Agent 插件：plugins/agents/*.py，继承 AgentPlugin
"""
from __future__ import annotations
import importlib.util, logging, sys, time
from pathlib import Path
from dataclasses import dataclass, field

from src.settings import settings
from src.tools.registry import Tool, register_tool_object, unregister_tool

logger = logging.getLogger("fiber.plugin")


class ToolPlugin:
    """Tool 插件基类。子类在 get_tools() 中返回 Tool 列表。"""
    name: str = "unnamed"
    version: str = "1.0.0"
    description: str = ""
    author: str = ""

    def get_tools(self) -> list[Tool]:
        raise NotImplementedError


@dataclass
class AgentPluginSpec:
    name: str
    description: str
    model_profile: str = "fast"
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""


class AgentPlugin:
    """Sub-Agent 插件基类。"""
    name: str = "unnamed"
    description: str = ""
    model_profile: str = "fast"
    tools: list[str] = []
    system_prompt: str = ""

    def spec(self) -> AgentPluginSpec:
        return AgentPluginSpec(self.name, self.description,
                               self.model_profile, self.tools,
                               self.system_prompt)


_LOADED: dict[str, dict] = {}   # plugin_name → {mtime, tools, agent}


def _load_module(path: Path):
    mod_name = f"fiber_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _scan_dir(directory: str, kind: str) -> None:
    d = Path(directory)
    if not d.exists():
        return
    for py in sorted(d.glob("*.py")):
        mtime = py.stat().st_mtime
        key = f"{kind}:{py.stem}"
        prev = _LOADED.get(key)
        if prev and prev["mtime"] >= mtime:
            continue   # 未变更
        # 卸载旧版本
        if prev:
            for tname in prev.get("tools", []):
                unregister_tool(tname)
            logger.info("插件热更新: %s", key)
        try:
            module = _load_module(py)
        except Exception as e:
            logger.error("插件加载失败 %s: %s", py, e)
            continue

        tool_names, agent_name = [], None
        for attr in vars(module).values():
            if isinstance(attr, type):
                if issubclass(attr, ToolPlugin) and attr is not ToolPlugin:
                    inst = attr()
                    for t in inst.get_tools():
                        t.plugin = inst.name
                        register_tool_object(t)
                        tool_names.append(t.name)
                    logger.info("插件 [%s v%s] 注册工具: %s",
                                inst.name, inst.version, tool_names)
                elif issubclass(attr, AgentPlugin) and attr is not AgentPlugin:
                    inst = attr()
                    from src.agents.sub_agents import SUBAGENTS, SubAgentSpec
                    s = inst.spec()
                    SUBAGENTS[s.name] = SubAgentSpec(
                        name=s.name, description=s.description,
                        model_profile=s.model_profile, tools=s.tools,
                        system_prompt=s.system_prompt)
                    agent_name = s.name
                    logger.info("插件注册 Sub-Agent: %s", s.name)
        _LOADED[key] = {"mtime": mtime, "tools": tool_names,
                        "agent": agent_name}


def discover_plugins() -> None:
    _scan_dir(settings.plugins["tools_dir"], "tool")
    _scan_dir(settings.plugins["agents_dir"], "agent")


def reload_plugins() -> dict:
    """强制重新扫描（API 触发）。"""
    discover_plugins()
    return {"loaded": list(_LOADED.keys())}


def list_plugins() -> list[dict]:
    return [{"key": k, **{kk: vv for kk, vv in v.items() if kk != "mtime"}}
            for k, v in _LOADED.items()]


async def plugin_watch_loop() -> None:
    """后台热加载扫描（默认 5s）。"""
    import asyncio
    interval = settings.plugins["scan_interval_seconds"]
    while True:
        await asyncio.sleep(interval)
        try:
            discover_plugins()
        except Exception as e:
            logger.error("插件扫描异常: %s", e)