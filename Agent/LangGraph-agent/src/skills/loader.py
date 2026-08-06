"""SkillLoader：扫描 → 解析 → 校验 → 注册。

启动时加载 skills/ 目录下所有 YAML 文件，
解析为 SkillDefinition 并注册到各 Registry。
支持热加载（reload）：原子切换，失败回滚。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from .schema import SkillDefinition

logger = logging.getLogger(__name__)


class SkillLoadError(Exception):
    """Skill 加载失败（热加载时整批拒绝）。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Skill load failed: {errors}")


class SkillLoader:
    """Skill 加载器：管理 YAML Skill 的生命周期。"""

    def __init__(self, skills_dir: Path):
        self._skills_dir = skills_dir
        self._registry: dict[str, SkillDefinition] = {}

    def load_all(self) -> int:
        """启动时加载所有 Skill，返回成功加载数量。"""
        self._registry.clear()
        errors: list[str] = []

        if not self._skills_dir.exists():
            logger.warning(f"[SkillLoader] Skills directory not found: {self._skills_dir}")
            return 0

        for path in sorted(self._skills_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue  # 跳过 _schema.json 等元文件
            try:
                skill = self._parse(path)
                if skill.id in self._registry:
                    logger.warning(f"[SkillLoader] Duplicate skill id '{skill.id}', overwriting")
                self._registry[skill.id] = skill
            except (ValidationError, yaml.YAMLError) as e:
                errors.append(f"{path.name}: {e}")
                logger.error(f"[SkillLoader] Failed to load {path.name}: {e}")

        if errors:
            logger.warning(f"[SkillLoader] {len(errors)} skill(s) failed to load")

        logger.info(f"[SkillLoader] Loaded {len(self._registry)} skills from {self._skills_dir}")
        return len(self._registry)

    def reload(self) -> int:
        """热加载：解析全部成功后原子切换，失败则保持旧注册表。"""
        if not self._skills_dir.exists():
            raise SkillLoadError([f"Skills directory not found: {self._skills_dir}"])

        new_registry: dict[str, SkillDefinition] = {}
        errors: list[str] = []

        for path in sorted(self._skills_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            try:
                skill = self._parse(path)
                new_registry[skill.id] = skill
            except (ValidationError, yaml.YAMLError) as e:
                errors.append(f"{path.name}: {e}")

        if errors:
            logger.error(f"[SkillLoader] Reload rejected ({len(errors)} errors): {errors}")
            raise SkillLoadError(errors)

        self._registry = new_registry
        if _loader_instance is self:
            # 仅全局单例同步全局 Registry；测试用独立实例不污染共享状态
            self._register_all()
        logger.info(f"[SkillLoader] Reloaded {len(self._registry)} skills")
        return len(self._registry)

    def get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        """按 id 获取已加载的 Skill。"""
        return self._registry.get(skill_id)

    def all_skills(self) -> list[SkillDefinition]:
        """返回所有已加载的 Skill。"""
        return list(self._registry.values())

    def get_tools_for_intent(self, intent: str) -> list[str]:
        """按意图返回 collector_tools 列表。"""
        for skill in self._registry.values():
            if skill.routing.intent == intent:
                return skill.collector_tools
        return []

    def _parse(self, path: Path) -> SkillDefinition:
        """解析单个 YAML 文件为 SkillDefinition。"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValidationError.from_exception_data(
                "SkillDefinition",
                [{"type": "dict_type", "loc": (), "msg": "Input should be a valid dict", "input": data}],
            )
        return SkillDefinition(**data)

    def _register_all(self) -> None:
        """将所有已加载 Skill 注册到各 Registry。"""
        registries = get_registries()
        # 清空所有注册表
        for reg in registries.values():
            reg.clear()
        # 逐个注册
        for skill in self._registry.values():
            registries["trigger"].register(skill)
            registries["routing"].register(skill)
            registries["template"].register(skill)
            registries["tool"].register(skill)
            registries["judgment"].register(skill)
            registries["test"].register(skill)
        logger.info(f"[SkillLoader] Registered {len(self._registry)} skills to registries")


# =============================================================================
# 全局 Registry 管理
# =============================================================================

_registry_instances: Optional[dict] = None


def get_registries() -> dict:
    """获取全局 Registry 实例字典。"""
    global _registry_instances
    if _registry_instances is None:
        from .registries import (
            JudgmentRegistry,
            RoutingRegistry,
            TemplateRegistry,
            TestRegistry,
            ToolRegistry,
            TriggerRegistry,
        )

        _registry_instances = {
            "trigger": TriggerRegistry(),
            "routing": RoutingRegistry(),
            "template": TemplateRegistry(),
            "tool": ToolRegistry(),
            "judgment": JudgmentRegistry(),
            "test": TestRegistry(),
        }
    return _registry_instances


# =============================================================================
# Singleton
# =============================================================================

_loader_instance: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """获取全局 SkillLoader 单例（首次调用时自动加载）。"""
    global _loader_instance
    if _loader_instance is None:
        from ..config import PROJECT_ROOT

        skills_dir = PROJECT_ROOT / "skills"
        _loader_instance = SkillLoader(skills_dir)
        _loader_instance.load_all()
        _loader_instance._register_all()
    return _loader_instance
