"""配置加载：YAML + ${ENV:default} 环境变量插值。"""
from __future__ import annotations
import os, re, yaml
from functools import lru_cache
from pathlib import Path
from typing import Any

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::([^}]*))?\}")

def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")
        return _ENV_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value

class Settings:
    def __init__(self, path: str | None = None):
        path = path or os.environ.get("FIBER_CONFIG", "config.yaml")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._cfg = _interpolate(raw)
        # 常用快捷访问
        self.app = self._cfg["app"]
        self.backend = self._cfg["backend"]
        self.llm = self._cfg["llm"]
        self.agents = self._cfg["agents"]
        self.rag = self._cfg["rag"]
        self.memory = self._cfg["memory"]
        self.sync = self._cfg["frontend_sync"]
        self.notify = self._cfg["notify"]
        self.plugins = self._cfg["plugins"]
        self.knowledge = self._cfg["knowledge"]
        # 目录预创建
        for d in (self.app["log_dir"], self.app["report_dir"],
                  self.app["data_dir"], self.knowledge["pending_dir"]):
            Path(d).mkdir(parents=True, exist_ok=True)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._cfg
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

@lru_cache
def _instance() -> Settings:
    return Settings()

settings = _instance()