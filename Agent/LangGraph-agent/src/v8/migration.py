"""
v8 灰度迁移配置 — 场景白名单 + 失败自动回退.

设计：
- v8_enabled_scenarios: 声明哪些场景走 v8 三层架构
- 未在白名单中的场景 → 回退 v7.1 图
- v8 执行失败（ERROR/异常）→ 自动回退 v7.1 重跑
- 灰度期结束后移除 v7.1 代码，白名单变为全量

配置来源：环境变量 V8_SCENARIOS（逗号分隔）或默认全量。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 默认启用的场景（灰度初期只开核心场景）
_DEFAULT_V8_SCENARIOS = {
    "spanloss_check",
    "oop_check",
    "iop_check",
    "performance_query",
    "fiber_status",
    "alarm_check",
    "alarm_batch_check",
    "topology_query",
}

# 全局缓存
_v8_scenarios: Optional[set[str]] = None


def get_v8_scenarios() -> set[str]:
    """获取 v8 启用的场景白名单."""
    global _v8_scenarios
    if _v8_scenarios is not None:
        return _v8_scenarios

    env_val = os.environ.get("V8_SCENARIOS", "")
    if env_val.strip() == "*":
        # 全量启用
        _v8_scenarios = {"*"}
        logger.info("[Migration] V8_SCENARIOS=*, all scenarios enabled")
    elif env_val.strip():
        _v8_scenarios = {s.strip() for s in env_val.split(",") if s.strip()}
        logger.info(f"[Migration] V8 scenarios: {_v8_scenarios}")
    else:
        _v8_scenarios = _DEFAULT_V8_SCENARIOS.copy()
        logger.info(f"[Migration] Using default V8 scenarios: {_v8_scenarios}")

    return _v8_scenarios


def is_scenario_v8_enabled(scenario_id: str) -> bool:
    """检查场景是否在 v8 白名单中."""
    scenarios = get_v8_scenarios()
    if "*" in scenarios:
        return True
    return scenario_id in scenarios


def reset_v8_scenarios() -> None:
    """重置缓存（测试用）."""
    global _v8_scenarios
    _v8_scenarios = None
