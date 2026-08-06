"""
Prompt 版本管理 — 将 prompts/VERSION 注入每次请求 trace。

出问题时可以说"是 v2.3 的 Prompt 引入的"。
"""
from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_VERSION_FILE = _PROJECT_ROOT / "prompts" / "VERSION"


def get_prompt_version() -> str:
    """读取当前 Prompt 版本号。"""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "unknown"
