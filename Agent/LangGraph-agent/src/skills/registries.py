"""6 个 Registry：连接 SkillLoader 与各消费组件。

每个 Registry 负责一个扩展点的注册和查询：
- TriggerRegistry → RuleEngine（触发匹配）
- RoutingRegistry → route_by_intent（意图路由）
- TemplateRegistry → FastPathExecutor（输出模板）
- ToolRegistry → FastPathExecutor（API 调用）
- JudgmentRegistry → JudgmentEngine（阈值判断）
- TestRegistry → pytest（自动回归）
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .schema import SkillDefinition

logger = logging.getLogger(__name__)

# 颜色归一化：与 ParamGate._COLOR_MAP 同契约，触发器提取的 color 统一强类型化
_COLOR_MAP = {
    "红色": "RED",
    "红": "RED",
    "red": "RED",
    "黄色": "YELLOW",
    "黄": "YELLOW",
    "yellow": "YELLOW",
    "绿色": "GREEN",
    "绿": "GREEN",
    "green": "GREEN",
}


# =============================================================================
# 触发规则注册表 → 规则引擎
# =============================================================================


class TriggerRegistry:
    """触发规则注册表：存储编译后的正则，供 RuleEngine.match() 使用。"""

    def __init__(self):
        self._compiled: list[tuple[int, dict, re.Pattern]] = []  # (priority, entry, pattern)
        self._sorted = False

    def register(self, skill: SkillDefinition) -> None:
        """从 Skill 的 triggers 字段注册触发规则。"""
        base_priority = skill.routing.priority
        for trigger in skill.triggers:
            # 触发级 priority 覆盖 routing 级
            priority = trigger.priority if trigger.priority is not None else base_priority
            entry = {
                "id": skill.id,
                "intent": skill.routing.intent,
                "params": trigger.params,
                "confidence": trigger.confidence,
                "template_id": skill.routing.template_id,
                "fast_path": skill.routing.fast_path_eligible,
            }
            self._compiled.append((priority, entry, re.compile(trigger.pattern, re.IGNORECASE)))
        self._sorted = False

    def match(self, user_input: str) -> Optional[dict]:
        """尝试匹配用户输入，按优先级顺序匹配。"""
        if not self._sorted:
            self._compiled.sort(key=lambda x: x[0])  # 按 priority 升序
            self._sorted = True
        text = user_input.strip()
        for _priority, entry, pattern in self._compiled:
            m = pattern.search(text)
            if m:
                try:
                    params = {}
                    for name, param_def in entry["params"].items():
                        if param_def.value is not None:
                            params[name] = param_def.value  # 静态值（如断纤 color=RED）
                            continue
                        raw = m.group(param_def.group)
                        params[name] = self._convert(raw, param_def.type)
                    return {
                        "intent": entry["intent"],
                        "params": params,
                        "confidence": entry["confidence"],
                        "template_id": entry["template_id"],
                        "fast_path_eligible": entry["fast_path"],
                    }
                except (ValueError, IndexError, AttributeError):
                    continue
        return None

    def clear(self) -> None:
        self._compiled.clear()
        self._sorted = False

    @staticmethod
    def _convert(raw: str, type_name: str) -> Any:
        """类型转换。int_list/int_range 供批量查询触发器提取 fiber_refs；
        color 归一化为 RED/YELLOW/GREEN 强类型（与 legacy 规则输出一致）。"""
        if type_name == "int":
            return int(raw)
        elif type_name == "float":
            return float(raw)
        elif type_name == "color":
            normalized = _COLOR_MAP.get(raw.strip().lower()) or _COLOR_MAP.get(raw.strip())
            if normalized is None:
                raise ValueError(f"unknown color '{raw}'")
            return normalized
        elif type_name == "int_list":
            nums = [int(x) for x in re.findall(r"\d+", raw)]
            if not nums:
                raise ValueError(f"no integer found in '{raw}'")
            return nums
        elif type_name == "int_range":
            nums = re.findall(r"\d+", raw)
            if len(nums) < 2:
                raise ValueError(f"range needs two integers, got '{raw}'")
            lo, hi = int(nums[0]), int(nums[1])
            if lo > hi or hi - lo > 200:
                raise ValueError(f"invalid range '{raw}'")
            return list(range(lo, hi + 1))
        return raw


# =============================================================================
# 路由注册表 → 意图路由
# =============================================================================


class RoutingRegistry:
    """路由注册表：intent → group 映射。"""

    def __init__(self):
        self._intent_to_group: dict[str, str] = {}

    def register(self, skill: SkillDefinition) -> None:
        self._intent_to_group[skill.routing.intent] = skill.routing.group

    def resolve(self, intent: str) -> str:
        """返回路由组名，未知意图返回 'chitchat'。"""
        return self._intent_to_group.get(intent, "chitchat")

    def clear(self) -> None:
        self._intent_to_group.clear()


# =============================================================================
# 模板注册表 → 快速路径执行器
# =============================================================================


class TemplateRegistry:
    """模板注册表：template_id → 模板配置。"""

    def __init__(self):
        self._templates: dict[str, dict] = {}

    def register(self, skill: SkillDefinition) -> None:
        if skill.template and skill.routing.template_id:
            self._templates[skill.routing.template_id] = {
                "fast_path": skill.template.fast_path,
                "status_map": skill.template.status_map,
            }

    def render(self, template_id: str, data: dict) -> str:
        """渲染模板。data 中应包含 status, fiber_id 等运行时字段。"""
        tmpl = self._templates.get(template_id)
        if not tmpl:
            return str(data.get("data", ""))[:500]
        try:
            status_text = tmpl["status_map"].get(data.get("status", ""), "")
            return tmpl["fast_path"].format(status_text=status_text, **data)
        except (KeyError, IndexError):
            return str(data.get("data", ""))[:500]

    def get_template(self, template_id: str) -> Optional[dict]:
        """获取模板配置。"""
        return self._templates.get(template_id)

    def clear(self) -> None:
        self._templates.clear()


# =============================================================================
# ToolRegistry → FastPathExecutor (API 调用)
# =============================================================================


class ToolRegistry:
    """工具注册表：intent → API 调用定义列表。"""

    def __init__(self):
        self._tools: dict[str, list[dict]] = {}

    def register(self, skill: SkillDefinition) -> None:
        if skill.tools:
            self._tools[skill.routing.intent] = [t.model_dump() for t in skill.tools]

    def get_tools(self, intent: str) -> list[dict]:
        """按意图获取工具定义列表。"""
        return self._tools.get(intent, [])

    def clear(self) -> None:
        self._tools.clear()


# =============================================================================
# 判定注册表 → 判定引擎
# =============================================================================


class JudgmentRegistry:
    """判断规则注册表：委托给 JudgmentEngine。"""

    def __init__(self):
        from .judgment_engine import JudgmentEngine

        self.engine = JudgmentEngine()

    def register(self, skill: SkillDefinition) -> None:
        if skill.judgment:
            j = skill.judgment
            self.engine.register_rule(
                metric=j.metric,
                extract_pattern=j.extract_pattern,
                conditions=j.conditions,
                default=j.default,
                actions=j.actions,
            )

    def clear(self) -> None:
        self.engine.clear()


# =============================================================================
# 测试注册表 → pytest
# =============================================================================


class TestRegistry:
    """测试用例注册表：收集所有 Skill 的 test_cases。"""

    def __init__(self):
        self._cases: list[tuple[str, dict]] = []

    def register(self, skill: SkillDefinition) -> None:
        for tc in skill.test_cases:
            self._cases.append((skill.id, tc.model_dump()))

    def all_cases(self) -> list[tuple[str, dict]]:
        return self._cases

    def clear(self) -> None:
        self._cases.clear()
