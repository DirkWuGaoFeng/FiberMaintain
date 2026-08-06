"""Skill YAML v8 兼容性测试."""
import pytest

from src.skills.loader import get_skill_loader


class TestV8SkillCompat:
    def test_loader_still_works(self):
        """现有 Skill 加载不受影响."""
        loader = get_skill_loader()
        skills = loader.all_skills()
        assert len(skills) > 0

    def test_spanloss_skill_has_routing(self):
        loader = get_skill_loader()
        # 通过 intent 查找
        for skill in loader.all_skills():
            if skill.routing.group == "data_query":
                assert skill.routing is not None
                assert len(skill.collector_tools) > 0
                break

    def test_v8_field_optional(self):
        """没有 v8 字段的 Skill 仍然正常."""
        loader = get_skill_loader()
        for skill in loader.all_skills():
            # v8 字段是可选的，不应报错
            assert skill.id != ""
            # v8 为 None 或有值都合法
            if skill.v8 is not None:
                assert skill.v8.max_loop_rounds >= 1
