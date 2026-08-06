"""从 Skill YAML 的 test_cases 字段自动生成回归测试。

新增 Skill 时，只要在 YAML 中写了 test_cases，测试自动覆盖。
无需编写 Python 测试代码。
"""

import pytest
from pathlib import Path

from src.skills.loader import SkillLoader
from src.skills.registries import TriggerRegistry


# =============================================================================
# 加载所有 Skill 并构建 TriggerRegistry
# =============================================================================

_skills_dir = Path(__file__).parent.parent / "skills"
_loader = SkillLoader(_skills_dir)
_loader.load_all()

_trigger_registry = TriggerRegistry()
for _skill in _loader.all_skills():
    _trigger_registry.register(_skill)

# 收集所有测试用例
_all_cases = [
    (skill.id, tc)
    for skill in _loader.all_skills()
    for tc in skill.test_cases
]


# =============================================================================
# 自动参数化测试
# =============================================================================


@pytest.mark.parametrize(
    "skill_id,test_case",
    _all_cases,
    ids=[f"{sid}:{tc.input}" for sid, tc in _all_cases],
)
def test_skill_trigger_match(skill_id: str, test_case):
    """自动回归：验证每个 Skill 的 test_cases 触发匹配。"""
    result = _trigger_registry.match(test_case.input)
    assert result is not None, f"Skill '{skill_id}': 未匹配输入 '{test_case.input}'"
    assert result["intent"] == test_case.expected_intent, (
        f"Skill '{skill_id}': 期望意图 '{test_case.expected_intent}', 实际 '{result['intent']}'"
    )
    if test_case.expected_params:
        assert result["params"] == test_case.expected_params, (
            f"Skill '{skill_id}': 期望参数 {test_case.expected_params}, 实际 {result['params']}"
        )
    assert result["fast_path_eligible"] == test_case.expected_fast_path, (
        f"Skill '{skill_id}': 期望 fast_path={test_case.expected_fast_path}, "
        f"实际 {result['fast_path_eligible']}"
    )


# =============================================================================
# 结构完整性测试
# =============================================================================


def test_all_skills_have_test_cases():
    """每个 Skill 应至少有一个测试用例。"""
    for skill in _loader.all_skills():
        assert len(skill.test_cases) >= 1, f"Skill '{skill.id}' 缺少 test_cases"


def test_skill_ids_unique():
    """所有 Skill ID 应唯一。"""
    ids = [s.id for s in _loader.all_skills()]
    assert len(ids) == len(set(ids)), f"重复的 Skill ID: {[x for x in ids if ids.count(x) > 1]}"


def test_minimum_skill_count():
    """应至少加载 13 个 Skill（覆盖原有 25+ 条规则）。"""
    count = len(_loader.all_skills())
    assert count >= 13, f"Expected >= 13 skills, got {count}"


def test_fast_path_skills_have_tools():
    """Fast Path Skill 应至少有一个 tool 定义。"""
    for skill in _loader.all_skills():
        if skill.routing.fast_path_eligible:
            assert len(skill.tools) >= 1, (
                f"Fast Path Skill '{skill.id}' 缺少 tools 定义"
            )


def test_normal_path_skills_have_collector_tools():
    """Normal Path Skill 应有 collector_tools。"""
    for skill in _loader.all_skills():
        if not skill.routing.fast_path_eligible and skill.routing.group == "data_query":
            assert len(skill.collector_tools) >= 1, (
                f"Normal Path Skill '{skill.id}' 缺少 collector_tools"
            )
