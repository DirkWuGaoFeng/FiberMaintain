"""Skill 系统单元测试。

覆盖：
- SkillDefinition Pydantic 模型验证
- SkillLoader 加载/热加载
- JudgmentEngine 声明式判断
- TriggerRegistry 触发匹配
"""

import pytest
from pathlib import Path


# =============================================================================
# Schema 测试
# =============================================================================


class TestSkillSchema:
    """SkillDefinition Pydantic 模型验证。"""

    def test_minimal_skill_parses(self):
        """最小合法 Skill 应成功解析。"""
        from src.skills.schema import SkillDefinition

        data = {
            "id": "test_query",
            "name": "测试查询",
            "version": "1.0",
            "triggers": [
                {
                    "pattern": r"测试\s*(\d+)",
                    "params": {"fiber_id": {"group": 1, "type": "int"}},
                    "confidence": 1.0,
                }
            ],
            "routing": {
                "intent": "test_query",
                "group": "data_query",
                "fast_path_eligible": True,
                "template_id": "T_TEST",
            },
            "tools": [
                {
                    "id": "query_test",
                    "endpoint": "/api/v1/test/{fiber_id}",
                    "method": "GET",
                    "timeout": 2.0,
                    "params": {"fiber_id": "{fiber_id}"},
                    "response_extract": {},
                }
            ],
        }
        skill = SkillDefinition(**data)
        assert skill.id == "test_query"
        assert skill.routing.fast_path_eligible is True
        assert len(skill.triggers) == 1
        assert skill.triggers[0].params["fiber_id"].group == 1

    def test_missing_required_field_fails(self):
        """缺少必填字段应抛出 ValidationError。"""
        from pydantic import ValidationError
        from src.skills.schema import SkillDefinition

        with pytest.raises(ValidationError):
            SkillDefinition(id="bad", name="bad")  # 缺少 triggers, routing

    def test_judgment_config_optional(self):
        """judgment 字段应为可选。"""
        from src.skills.schema import SkillDefinition

        data = {
            "id": "no_judgment",
            "name": "无判断",
            "version": "1.0",
            "triggers": [{"pattern": "test", "params": {}, "confidence": 1.0}],
            "routing": {
                "intent": "no_judgment",
                "group": "knowledge",
                "fast_path_eligible": False,
                "template_id": "",
            },
            "tools": [],
        }
        skill = SkillDefinition(**data)
        assert skill.judgment is None
        assert skill.template is None
        assert skill.collector_tools == []


# =============================================================================
# SkillLoader 测试
# =============================================================================


class TestSkillLoader:
    """SkillLoader 加载和解析测试。"""

    def test_load_single_yaml(self, tmp_path):
        """应成功加载单个合法 YAML 文件。"""
        from src.skills.loader import SkillLoader

        yaml_content = """\
id: test_skill
name: 测试
version: "1.0"
triggers:
  - pattern: "测试(\\\\d+)"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0
routing:
  intent: test_skill
  group: data_query
  fast_path_eligible: true
  template_id: T_TEST
tools:
  - id: query_test
    endpoint: "/api/v1/test/{fiber_id}"
    method: GET
    timeout: 2.0
    params: { fiber_id: "{fiber_id}" }
    response_extract: {}
"""
        (tmp_path / "test_skill.yaml").write_text(yaml_content, encoding="utf-8")
        loader = SkillLoader(tmp_path)
        count = loader.load_all()
        assert count == 1
        skill = loader.get_skill("test_skill")
        assert skill is not None
        assert skill.name == "测试"

    def test_invalid_yaml_skipped(self, tmp_path):
        """非法 YAML 应跳过并记录错误，不影响其他 Skill。"""
        from src.skills.loader import SkillLoader

        # 缺少必填字段 triggers
        (tmp_path / "bad.yaml").write_text("id: bad\nname: bad\n", encoding="utf-8")
        loader = SkillLoader(tmp_path)
        count = loader.load_all()
        assert count == 0

    def test_reload_replaces_registry(self, tmp_path):
        """reload 应清空旧注册表并重新加载。"""
        from src.skills.loader import SkillLoader

        yaml_content = """\
id: reload_test
name: V1
version: "1.0"
triggers:
  - pattern: "test"
    params: {}
    confidence: 1.0
routing:
  intent: reload_test
  group: data_query
  fast_path_eligible: false
  template_id: ""
tools: []
"""
        (tmp_path / "skill.yaml").write_text(yaml_content, encoding="utf-8")
        loader = SkillLoader(tmp_path)
        loader.load_all()
        assert loader.get_skill("reload_test").name == "V1"

        # 修改文件后 reload
        (tmp_path / "skill.yaml").write_text(yaml_content.replace("V1", "V2"), encoding="utf-8")
        loader.reload()
        assert loader.get_skill("reload_test").name == "V2"

    def test_reload_rejects_on_error(self, tmp_path):
        """reload 时如果新文件非法，应保持旧注册表。"""
        from src.skills.loader import SkillLoader, SkillLoadError

        yaml_content = """\
id: good_skill
name: Good
version: "1.0"
triggers:
  - pattern: "good"
    params: {}
    confidence: 1.0
routing:
  intent: good_skill
  group: data_query
  fast_path_eligible: false
  template_id: ""
tools: []
"""
        (tmp_path / "good.yaml").write_text(yaml_content, encoding="utf-8")
        loader = SkillLoader(tmp_path)
        loader.load_all()
        assert loader.get_skill("good_skill") is not None

        # 添加一个非法文件
        (tmp_path / "bad.yaml").write_text("id: bad\n", encoding="utf-8")
        with pytest.raises(SkillLoadError):
            loader.reload()

        # 旧注册表保持不变
        assert loader.get_skill("good_skill") is not None

    def test_load_real_skills_dir(self):
        """应成功加载项目 skills/ 目录下的所有 YAML。"""
        from src.skills.loader import SkillLoader

        skills_dir = Path(__file__).parent.parent / "skills"
        if not skills_dir.exists():
            pytest.skip("skills/ directory not found")
        loader = SkillLoader(skills_dir)
        count = loader.load_all()
        assert count >= 1


# =============================================================================
# JudgmentEngine 测试
# =============================================================================


class TestJudgmentEngine:
    """声明式判断引擎测试。"""

    def test_spanloss_critical(self):
        """spanloss > 8.0 应返回 CRITICAL。"""
        from src.skills.judgment_engine import JudgmentEngine
        from src.skills.schema import JudgmentCondition, JudgmentDefault

        engine = JudgmentEngine()
        engine.register_rule(
            metric="spanloss",
            extract_pattern=r"spanloss[=:]\s*([\d.]+)",
            conditions=[
                JudgmentCondition(op=">", value="8.0", status="CRITICAL", finding="衰耗 {value}dB 严重超标"),
                JudgmentCondition(op=">", value="5.0", status="WARNING", finding="衰耗 {value}dB 超阈值"),
            ],
            default=JudgmentDefault(status="NORMAL", finding="衰耗 {value}dB 正常"),
            actions={"CRITICAL": ["立即派单"], "WARNING": ["列入巡检"]},
        )

        result = engine.evaluate("spanloss=9.5")
        assert result["status"] == "CRITICAL"
        assert "严重超标" in result["findings"][0]
        assert result["metrics"]["spanloss"] == 9.5
        assert "立即派单" in result["actions"]

    def test_spanloss_warning(self):
        """5.0 < spanloss < 8.0 应返回 WARNING。"""
        from src.skills.judgment_engine import JudgmentEngine
        from src.skills.schema import JudgmentCondition, JudgmentDefault

        engine = JudgmentEngine()
        engine.register_rule(
            metric="spanloss",
            extract_pattern=r"spanloss[=:]\s*([\d.]+)",
            conditions=[
                JudgmentCondition(op=">", value="8.0", status="CRITICAL", finding="严重超标"),
                JudgmentCondition(op=">", value="5.0", status="WARNING", finding="超阈值"),
            ],
            default=JudgmentDefault(status="NORMAL", finding="正常"),
            actions={"WARNING": ["列入巡检"]},
        )

        result = engine.evaluate("spanloss=6.2")
        assert result["status"] == "WARNING"
        assert "超阈值" in result["findings"][0]

    def test_spanloss_normal(self):
        """spanloss < 5.0 应返回 NORMAL。"""
        from src.skills.judgment_engine import JudgmentEngine
        from src.skills.schema import JudgmentCondition, JudgmentDefault

        engine = JudgmentEngine()
        engine.register_rule(
            metric="spanloss",
            extract_pattern=r"spanloss[=:]\s*([\d.]+)",
            conditions=[
                JudgmentCondition(op=">", value="8.0", status="CRITICAL", finding="严重超标"),
                JudgmentCondition(op=">", value="5.0", status="WARNING", finding="超阈值"),
            ],
            default=JudgmentDefault(status="NORMAL", finding="衰耗 {value}dB 正常"),
            actions={},
        )

        result = engine.evaluate("spanloss=3.2")
        assert result["status"] == "NORMAL"
        assert "正常" in result["findings"][0]

    def test_no_match_returns_empty(self):
        """data_summary 中无匹配指标时应返回空 findings。"""
        from src.skills.judgment_engine import JudgmentEngine
        from src.skills.schema import JudgmentCondition, JudgmentDefault

        engine = JudgmentEngine()
        engine.register_rule(
            metric="spanloss",
            extract_pattern=r"spanloss[=:]\s*([\d.]+)",
            conditions=[],
            default=JudgmentDefault(),
            actions={},
        )

        result = engine.evaluate("no relevant data here")
        assert result["status"] == "NORMAL"
        assert result["findings"] == []
        assert result["metrics"] == {}


# =============================================================================
# TriggerRegistry 测试
# =============================================================================


class TestTriggerRegistry:
    """触发规则注册和匹配测试。"""

    def test_match_from_real_skill(self):
        """从真实 spanloss_query.yaml 加载后应能匹配。"""
        from src.skills.loader import SkillLoader
        from src.skills.registries import TriggerRegistry

        skills_dir = Path(__file__).parent.parent / "skills"
        if not skills_dir.exists():
            pytest.skip("skills/ directory not found")

        loader = SkillLoader(skills_dir)
        loader.load_all()

        registry = TriggerRegistry()
        for skill in loader.all_skills():
            registry.register(skill)

        result = registry.match("查光纤 3 的衰耗")
        assert result is not None
        assert result["intent"] == "spanloss_query"
        assert result["params"]["fiber_id"] == 3
        assert result["fast_path_eligible"] is True

    def test_no_match_returns_none(self):
        """不匹配的输入应返回 None。"""
        from src.skills.registries import TriggerRegistry

        registry = TriggerRegistry()
        result = registry.match("今天天气怎么样")
        assert result is None
