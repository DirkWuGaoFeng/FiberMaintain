"""
用户记忆管理器 (UserMemory).

【设计原则】
对应 AI Agent 设计原则 Chapter 3 用户记忆系统：
  - 与 ExperienceStore（集体经验）区分，专用于用户个性化
  - 零 LLM 开销：纯规则匹配注入偏好
  - 偏好注入到 ExpressionAgent 输出格式选择
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.memory.user_memory_store import UserMemoryStore

logger = logging.getLogger(__name__)


class UserMemory(BaseModel):
    """用户记忆模型."""

    user_id: str
    preferences: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    last_session: str = ""
    memory_version: int = 1


class UserMemoryManager:
    """用户记忆管理器."""

    def __init__(self, store: Optional[UserMemoryStore] = None):
        self._store = store or UserMemoryStore()
        self._cache: dict[str, UserMemory] = {}

    def get_memory(self, user_id: str) -> UserMemory:
        """获取用户记忆（优先缓存）."""
        if user_id in self._cache:
            return self._cache[user_id]

        raw = self._store.load(user_id)
        if raw:
            memory = UserMemory(**raw)
        else:
            memory = UserMemory(user_id=user_id)
        self._cache[user_id] = memory
        return memory

    def update_preference(self, user_id: str, key: str, value: Any) -> UserMemory:
        """更新单个偏好."""
        self._store.update_preferences(user_id, {key: value})
        if user_id in self._cache:
            self._cache[user_id].preferences[key] = value
        memory = self.get_memory(user_id)
        logger.debug(f"[UserMemory] Updated preference {key}={value} for {user_id}")
        return memory

    def record_event(self, user_id: str, event_type: str, details: dict[str, Any]) -> None:
        """记录用户事件."""
        event = {
            "event_type": event_type,
            "details": details,
            "ts": __import__("time").time(),
        }
        self._store.add_history(user_id, event)
        self._store.log_event(user_id, event_type, details)
        # 刷新缓存
        if user_id in self._cache:
            raw = self._store.load(user_id)
            if raw:
                self._cache[user_id] = UserMemory(**raw)

    def inject_preferences(self, user_id: str, context: dict[str, Any]) -> dict[str, Any]:
        """将用户偏好注入到上下文（零 LLM 开销）."""
        memory = self.get_memory(user_id)
        if not memory.preferences:
            return context

        enriched = dict(context)

        # 输出格式偏好
        default_format = memory.preferences.get("default_format")
        if default_format and "output_format" not in enriched:
            enriched["output_format"] = default_format

        # 通知级别偏好
        notify_severity = memory.preferences.get("notify_severity")
        if notify_severity:
            enriched["notify_severity"] = notify_severity

        # 语言偏好
        language = memory.preferences.get("language")
        if language:
            enriched["language"] = language

        # 自定义偏好字段
        custom = memory.preferences.get("custom_fields", {})
        if custom:
            enriched["user_preferences"] = custom

        return enriched

    def clear_cache(self, user_id: Optional[str] = None) -> None:
        """清缓存."""
        if user_id:
            self._cache.pop(user_id, None)
        else:
            self._cache.clear()

    def delete_user(self, user_id: str) -> None:
        """删除用户记忆."""
        self._store.delete_user(user_id)
        self._cache.pop(user_id, None)


_manager: Optional[UserMemoryManager] = None


def get_user_memory_manager() -> UserMemoryManager:
    """获取用户记忆管理器单例."""
    global _manager
    if _manager is None:
        _manager = UserMemoryManager()
    return _manager
