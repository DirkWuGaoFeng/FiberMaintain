# 配置化 Skill + 声明式规则引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将散落在 9 个 Python 文件中的扩展点收敛到单一 YAML Skill 文件，实现"新增场景 = 写 1 个 YAML"。

**Architecture:** SkillLoader 在启动时扫描 `skills/` 目录，解析 YAML 为 Pydantic 强类型模型，分发注册到 6 个 Registry（Trigger/Tool/Judgment/Template/Routing/Test）。各消费节点从 Registry 读取配置而非硬编码。JudgmentEngine 作为通用声明式判断引擎，Fast Path 和 Normal Path 共用。

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, FastAPI, pytest, LangChain @tool

**Spec:** `Agent/docs/2026-08-02-skill-system-design.md`

---

## File Structure

| 文件 | 职责 |
|------|------|
| `src/skills/__init__.py` | 模块导出 |
| `src/skills/schema.py` | Pydantic 模型：SkillDefinition, TriggerRule, ToolDefinition, JudgmentConfig, TemplateConfig, RoutingConfig, TestCase |
| `src/skills/loader.py` | SkillLoader：扫描/解析/校验/注册/热加载 |
| `src/skills/registries.py` | 6 个 Registry：TriggerRegistry, ToolRegistry, JudgmentRegistry, TemplateRegistry, RoutingRegistry, TestRegistry |
| `src/skills/judgment_engine.py` | JudgmentEngine：通用声明式阈值判断 |
| `skills/*.yaml` | 16 个 Skill 定义文件 |
| `skills/_schema.json` | JSON Schema（IDE 提示） |
| `tests/test_skills.py` | Skill 系统单元测试 |
| `tests/test_skills_auto.py` | 从 YAML test_cases 自动生成的回归测试 |

---

## Phase 1: 搭建骨架

### Task 1: Pydantic Schema 模型

**Files:**
- Create: `src/skills/__init__.py`
- Create: `src/skills/schema.py`
- Test: `tests/test_skills.py`

- [ ] **Step 1: 创建模块目录和 __init__.py**

```python
# src/skills/__init__.py
"""配置化 Skill 系统 — 声明式场景扩展机制。"""

from .schema import SkillDefinition
from .loader import SkillLoader, get_skill_loader

__all__ = ["SkillDefinition", "SkillLoader", "get_skill_loader"]
```

- [ ] **Step 2: 编写 schema.py 的失败测试**

```python
# tests/test_skills.py
"""Skill 系统单元测试。"""
import pytest
from pathlib import Path


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
                {"pattern": r"测试\s*(\d+)", "params": {"fiber_id": {"group": 1, "type": "int"}}, "confidence": 1.0}
            ],
            "routing": {"intent": "test_query", "group": "data_query", "fast_path_eligible": True, "template_id": "T_TEST"},
            "tools": [
                {"id": "query_test", "endpoint": "/api/v1/test/{fiber_id}", "method": "GET", "timeout": 2.0, "params": {"fiber_id": "{fiber_id}"}, "response_extract": {}}
            ],
        }
        skill = SkillDefinition(**data)
        assert skill.id == "test_query"
        assert skill.routing.fast_path_eligible is True
        assert len(skill.triggers) == 1

    def test_missing_required_field_fails(self):
        """缺少必填字段应抛出 ValidationError。"""
        from pydantic import ValidationError
        from src.skills.schema import SkillDefinition

        with pytest.raises(ValidationError):
            SkillDefinition(id="bad", name="bad")  # 缺少 triggers, routing, tools

    def test_judgment_config_optional(self):
        """judgment 字段应为可选。"""
        from src.skills.schema import SkillDefinition

        data = {
            "id": "no_judgment",
            "name": "无判断",
            "version": "1.0",
            "triggers": [{"pattern": "test", "params": {}, "confidence": 1.0}],
            "routing": {"intent": "no_judgment", "group": "knowledge", "fast_path_eligible": False, "template_id": ""},
            "tools": [],
        }
        skill = SkillDefinition(**data)
        assert skill.judgment is None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.skills'`

- [ ] **Step 4: 实现 schema.py**

```python
# src/skills/schema.py
"""Skill YAML 的 Pydantic 强类型模型定义。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TriggerParam(BaseModel):
    """触发规则中的参数提取定义。"""
    group: int = Field(description="正则捕获组编号")
    type: Literal["int", "str", "float"] = Field(default="str", description="类型转换")


class TriggerRule(BaseModel):
    """触发规则：正则 + 参数提取。"""
    pattern: str = Field(description="正则表达式")
    params: dict[str, TriggerParam] = Field(default_factory=dict, description="参数提取映射")
    confidence: float = Field(default=1.0, description="置信度")


class RoutingConfig(BaseModel):
    """路由配置。"""
    intent: str = Field(description="意图标识")
    group: Literal["data_query", "batch", "knowledge", "report", "chitchat"] = Field(description="路由组")
    fast_path_eligible: bool = Field(default=False, description="是否可走 Fast Path")
    template_id: str = Field(default="", description="Fast Path 模板 ID")


class ToolDefinition(BaseModel):
    """工具定义：API 调用描述。"""
    id: str = Field(description="工具标识")
    endpoint: str = Field(description="API 路径（支持 {param} 占位符）")
    method: Literal["GET", "POST"] = Field(default="GET")
    timeout: float = Field(default=2.0, description="超时秒数")
    params: dict[str, str] = Field(default_factory=dict, description="请求参数")
    response_extract: dict[str, str] = Field(default_factory=dict, description="JSONPath 提取")


class JudgmentCondition(BaseModel):
    """判断条件。"""
    op: Literal[">", "<", "not_in_range", "contains", "==", "count_gt"] = Field(description="操作符")
    value: str = Field(description="阈值（支持 ${CONFIG_VAR}）")
    status: Literal["CRITICAL", "WARNING", "NORMAL"] = Field(description="状态")
    finding: str = Field(description="判断结论模板")


class JudgmentDefault(BaseModel):
    """判断默认值。"""
    status: Literal["CRITICAL", "WARNING", "NORMAL"] = Field(default="NORMAL")
    finding: str = Field(default="未发现明显异常")


class JudgmentConfig(BaseModel):
    """判断规则配置。"""
    metric: str = Field(description="指标名称")
    extract_pattern: str = Field(description="从 data_summary 提取值的正则")
    conditions: list[JudgmentCondition] = Field(default_factory=list, description="条件列表（按优先级）")
    default: JudgmentDefault = Field(default_factory=JudgmentDefault)
    actions: dict[str, list[str]] = Field(default_factory=dict, description="按 status 的建议动作")


class TemplateConfig(BaseModel):
    """输出模板配置。"""
    fast_path: str = Field(default="{data}", description="Fast Path 输出模板")
    status_map: dict[str, str] = Field(default_factory=dict, description="status → 状态文本")


class TestCase(BaseModel):
    """Skill 测试用例。"""
    input: str = Field(description="用户输入")
    expected_intent: str = Field(description="期望意图")
    expected_params: dict[str, Any] = Field(default_factory=dict, description="期望参数")
    expected_fast_path: bool = Field(default=False, description="期望是否走 Fast Path")


class SkillDefinition(BaseModel):
    """Skill 完整定义 — 一个 YAML 文件的 Pydantic 映射。"""
    id: str = Field(description="唯一标识")
    name: str = Field(description="显示名称")
    version: str = Field(default="1.0")
    description: str = Field(default="")
    author: str = Field(default="")
    triggers: list[TriggerRule] = Field(min_length=1, description="触发规则列表")
    routing: RoutingConfig = Field(description="路由配置")
    tools: list[ToolDefinition] = Field(default_factory=list, description="工具定义")
    judgment: Optional[JudgmentConfig] = Field(default=None, description="判断规则")
    template: Optional[TemplateConfig] = Field(default=None, description="输出模板")
    collector_tools: list[str] = Field(default_factory=list, description="Normal Path 工具组")
    test_cases: list[TestCase] = Field(default_factory=list, description="测试用例")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/skills/__init__.py src/skills/schema.py tests/test_skills.py
git commit -m "feat(skills): add Pydantic schema for Skill YAML definitions"
```

---

### Task 2: SkillLoader 核心

**Files:**
- Create: `src/skills/loader.py`
- Create: `skills/spanloss_query.yaml` (第一个示例 Skill)
- Test: `tests/test_skills.py` (追加)

- [ ] **Step 1: 创建示例 Skill YAML**

```yaml
# skills/spanloss_query.yaml
id: spanloss_query
name: 光纤衰耗查询
version: "1.0"
description: "查询单条光纤的跨段衰耗值并做阈值判断"
author: "fiber-team"

triggers:
  - pattern: "(?:查|看|查询|查一下)\\s*(?:光纤|FIB)[-_]?\\s*(\\d+)\\s*(?:的)?\\s*(?:跨段)?(?:衰耗|spanloss|损耗)"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0
  - pattern: "(?:光纤|连纤|FIB)[-_]?\\s*(\\d+)\\s*(?:的)?\\s*(?:衰耗|损耗|spanloss)"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0

routing:
  intent: spanloss_query
  group: data_query
  fast_path_eligible: true
  template_id: T_SPANLOSS

tools:
  - id: query_spanloss
    endpoint: "/api/v1/fibers/{fiber_id}/spanloss"
    method: GET
    timeout: 2.0
    params:
      fiber_id: "{fiber_id}"
    response_extract:
      spanloss: "$.spanloss"

judgment:
  metric: spanloss
  extract_pattern: "spanloss[=:]\\s*([\\d.]+)"
  conditions:
    - op: ">"
      value: "${SPANLOSS_CRITICAL}"
      status: CRITICAL
      finding: "衰耗 {value}dB 严重超标（阈值 ${SPANLOSS_THRESHOLD}dB，超出 {percent}%）"
    - op: ">"
      value: "${SPANLOSS_THRESHOLD}"
      status: WARNING
      finding: "衰耗 {value}dB 超过阈值 ${SPANLOSS_THRESHOLD}dB"
  default:
    status: NORMAL
    finding: "衰耗 {value}dB，在阈值 ${SPANLOSS_THRESHOLD}dB 内，正常"
  actions:
    CRITICAL: ["立即派单检修", "检查关联光纤", "通知值班主管"]
    WARNING: ["列入巡检计划", "持续监控趋势"]

template:
  fast_path: "光纤 {fiber_id} 当前衰耗为 {spanloss} dB（阈值 ${SPANLOSS_THRESHOLD} dB），{status_text}。"
  status_map:
    CRITICAL: "⚠️ 严重超标，建议立即检修"
    WARNING: "⚡ 超过阈值，建议关注"
    NORMAL: "✅ 正常"

collector_tools:
  - fiber_spanloss_query
  - fiber_performance_query
  - alarm_query

test_cases:
  - input: "查光纤 3 的衰耗"
    expected_intent: spanloss_query
    expected_params: { fiber_id: 3 }
    expected_fast_path: true
  - input: "FIB-005 spanloss 多少"
    expected_intent: spanloss_query
    expected_params: { fiber_id: 5 }
    expected_fast_path: true
  - input: "光纤12的跨段损耗"
    expected_intent: spanloss_query
    expected_params: { fiber_id: 12 }
    expected_fast_path: true
```

- [ ] **Step 2: 编写 SkillLoader 的失败测试**

```python
# tests/test_skills.py (追加)

class TestSkillLoader:
    """SkillLoader 加载和解析测试。"""

    def test_load_single_yaml(self, tmp_path):
        """应成功加载单个合法 YAML 文件。"""
        from src.skills.loader import SkillLoader

        yaml_content = """
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

        (tmp_path / "bad.yaml").write_text("id: bad\nname: bad\n", encoding="utf-8")
        loader = SkillLoader(tmp_path)
        count = loader.load_all()
        assert count == 0

    def test_reload_replaces_registry(self, tmp_path):
        """reload 应清空旧注册表并重新加载。"""
        from src.skills.loader import SkillLoader

        yaml_content = """
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

    def test_load_real_skills_dir(self):
        """应成功加载项目 skills/ 目录下的所有 YAML。"""
        from pathlib import Path
        from src.skills.loader import SkillLoader

        skills_dir = Path(__file__).parent.parent / "skills"
        if not skills_dir.exists():
            pytest.skip("skills/ directory not found")
        loader = SkillLoader(skills_dir)
        count = loader.load_all()
        assert count >= 1
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py::TestSkillLoader -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.skills.loader'`

- [ ] **Step 4: 实现 loader.py**

```python
# src/skills/loader.py
"""SkillLoader：扫描 → 解析 → 校验 → 注册。"""

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
            raise ValidationError.from_exception_data("SkillDefinition", [])
        return SkillDefinition(**data)


# =============================================================================
# Singleton
# =============================================================================

_loader_instance: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """获取全局 SkillLoader 单例。"""
    global _loader_instance
    if _loader_instance is None:
        from ..config import PROJECT_ROOT
        skills_dir = PROJECT_ROOT / "skills"
        _loader_instance = SkillLoader(skills_dir)
        _loader_instance.load_all()
    return _loader_instance
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/skills/loader.py skills/spanloss_query.yaml tests/test_skills.py
git commit -m "feat(skills): add SkillLoader with YAML parsing and hot-reload"
```

---

### Task 3: 6 个 Registry + JudgmentEngine

**Files:**
- Create: `src/skills/registries.py`
- Create: `src/skills/judgment_engine.py`
- Test: `tests/test_skills.py` (追加)

- [ ] **Step 1: 编写 JudgmentEngine 的失败测试**

```python
# tests/test_skills.py (追加)

class TestJudgmentEngine:
    """声明式判断引擎测试。"""

    def test_spanloss_critical(self):
        """spanloss > SPANLOSS_CRITICAL 应返回 CRITICAL。"""
        from src.skills.judgment_engine import JudgmentEngine
        from src.skills.schema import JudgmentConfig, JudgmentCondition, JudgmentDefault

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

    def test_spanloss_normal(self):
        """spanloss < threshold 应返回 NORMAL。"""
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py::TestJudgmentEngine -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 judgment_engine.py**

```python
# src/skills/judgment_engine.py
"""声明式判断引擎 — 通用阈值评估。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .schema import JudgmentCondition, JudgmentDefault

logger = logging.getLogger(__name__)

# 状态优先级
_STATUS_PRIORITY = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


@dataclass
class JudgmentRule:
    """一条判断规则。"""
    metric: str
    extract_pattern: re.Pattern
    conditions: list[JudgmentCondition]
    default: JudgmentDefault
    actions: dict[str, list[str]]


class JudgmentEngine:
    """通用声明式判断引擎。"""

    def __init__(self):
        self._rules: list[JudgmentRule] = []

    def register_rule(
        self,
        metric: str,
        extract_pattern: str,
        conditions: list[JudgmentCondition],
        default: JudgmentDefault,
        actions: dict[str, list[str]],
    ) -> None:
        """注册一条判断规则。"""
        self._rules.append(JudgmentRule(
            metric=metric,
            extract_pattern=re.compile(extract_pattern, re.IGNORECASE),
            conditions=conditions,
            default=default,
            actions=actions,
        ))

    def clear(self) -> None:
        """清空所有规则（热加载前调用）。"""
        self._rules.clear()

    def evaluate(self, data_summary: str) -> dict[str, Any]:
        """对 data_summary 逐条规则匹配，返回结构化判断。"""
        findings: list[str] = []
        metrics: dict[str, float] = {}
        status = "NORMAL"
        all_actions: list[str] = []

        for rule in self._rules:
            value = self._extract(rule, data_summary)
            if value is None:
                continue

            metrics[rule.metric] = value
            result = self._evaluate_conditions(rule, value)
            findings.append(result["finding"])

            if _STATUS_PRIORITY.get(result["status"], 0) > _STATUS_PRIORITY.get(status, 0):
                status = result["status"]
                all_actions = rule.actions.get(status, [])

        return {
            "status": status,
            "findings": findings,
            "metrics": metrics,
            "actions": all_actions,
        }

    def _extract(self, rule: JudgmentRule, data: str) -> Optional[float]:
        """从 data_summary 中提取指标值。"""
        m = rule.extract_pattern.search(data)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                return None
        return None

    def _evaluate_conditions(self, rule: JudgmentRule, value: float) -> dict[str, str]:
        """按优先级评估条件。"""
        for cond in rule.conditions:
            threshold = self._resolve_value(cond.value)
            if self._compare(value, cond.op, threshold):
                finding = cond.finding.format(
                    value=value,
                    percent=round((value - threshold) / threshold * 100) if threshold else 0,
                )
                return {"status": cond.status, "finding": finding}

        # 默认
        finding = rule.default.finding.format(value=value)
        return {"status": rule.default.status, "finding": finding}

    def _compare(self, value: float, op: str, threshold: float) -> bool:
        """执行比较操作。"""
        if op == ">":
            return value > threshold
        elif op == "<":
            return value < threshold
        elif op == "==":
            return value == threshold
        elif op == "count_gt":
            return value > threshold
        return False

    def _resolve_value(self, raw: str) -> float:
        """解析条件值：${VAR} → config 环境变量。"""
        if raw.startswith("${") and raw.endswith("}"):
            var_name = raw[2:-1]
            from .. import config
            return float(getattr(config, var_name, 0))
        return float(raw)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py::TestJudgmentEngine -v`
Expected: 3 passed

- [ ] **Step 5: 实现 registries.py**

```python
# src/skills/registries.py
"""6 个 Registry：连接 SkillLoader 与各消费组件。"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .schema import SkillDefinition

logger = logging.getLogger(__name__)


class TriggerRegistry:
    """触发规则注册表 → 供 RuleEngine 使用。"""

    def __init__(self):
        self._compiled: list[tuple[dict, re.Pattern]] = []

    def register(self, skill: SkillDefinition) -> None:
        for trigger in skill.triggers:
            entry = {
                "id": skill.id,
                "intent": skill.routing.intent,
                "params": trigger.params,
                "confidence": trigger.confidence,
                "template_id": skill.routing.template_id,
                "fast_path": skill.routing.fast_path_eligible,
            }
            self._compiled.append((entry, re.compile(trigger.pattern, re.IGNORECASE)))

    def match(self, user_input: str) -> Optional[dict]:
        """尝试匹配，返回 RuleMatch 兼容的 dict 或 None。"""
        text = user_input.strip()
        for entry, pattern in self._compiled:
            m = pattern.search(text)
            if m:
                try:
                    params = {}
                    for name, param_def in entry["params"].items():
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

    @staticmethod
    def _convert(raw: str, type_name: str) -> Any:
        if type_name == "int":
            return int(raw)
        elif type_name == "float":
            return float(raw)
        return raw


class RoutingRegistry:
    """路由注册表 → 供 route_by_intent 使用。"""

    def __init__(self):
        self._intent_to_group: dict[str, str] = {}

    def register(self, skill: SkillDefinition) -> None:
        self._intent_to_group[skill.routing.intent] = skill.routing.group

    def resolve(self, intent: str) -> str:
        """返回路由组名。"""
        return self._intent_to_group.get(intent, "chitchat")

    def clear(self) -> None:
        self._intent_to_group.clear()


class TemplateRegistry:
    """模板注册表 → 供 FastPathExecutor 使用。"""

    def __init__(self):
        self._templates: dict[str, dict] = {}

    def register(self, skill: SkillDefinition) -> None:
        if skill.template:
            self._templates[skill.routing.template_id] = {
                "fast_path": skill.template.fast_path,
                "status_map": skill.template.status_map,
            }

    def render(self, template_id: str, data: dict) -> str:
        """渲染模板。"""
        tmpl = self._templates.get(template_id)
        if not tmpl:
            return str(data.get("data", ""))[:500]
        try:
            status_text = tmpl["status_map"].get(data.get("status", ""), "")
            return tmpl["fast_path"].format(status_text=status_text, **data)
        except (KeyError, IndexError):
            return str(data.get("data", ""))[:500]

    def clear(self) -> None:
        self._templates.clear()


class ToolRegistry:
    """工具注册表 → 供 FastPathExecutor 直接调用 API。"""

    def __init__(self):
        self._tools: dict[str, list[dict]] = {}  # intent → tool definitions

    def register(self, skill: SkillDefinition) -> None:
        if skill.tools:
            self._tools[skill.routing.intent] = [t.model_dump() for t in skill.tools]

    def get_tools(self, intent: str) -> list[dict]:
        return self._tools.get(intent, [])

    def clear(self) -> None:
        self._tools.clear()


class JudgmentRegistry:
    """判断规则注册表 → 委托给 JudgmentEngine。"""

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


class TestRegistry:
    """测试用例注册表 → 供 pytest 参数化使用。"""

    def __init__(self):
        self._cases: list[tuple[str, dict]] = []  # (skill_id, test_case)

    def register(self, skill: SkillDefinition) -> None:
        for tc in skill.test_cases:
            self._cases.append((skill.id, tc.model_dump()))

    def all_cases(self) -> list[tuple[str, dict]]:
        return self._cases

    def clear(self) -> None:
        self._cases.clear()
```

- [ ] **Step 6: 运行全部测试**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/skills/registries.py src/skills/judgment_engine.py tests/test_skills.py
git commit -m "feat(skills): add 6 registries and declarative JudgmentEngine"
```

---

## Phase 2: 改造消费端

### Task 4: RuleEngine 从 TriggerRegistry 读取

**Files:**
- Modify: `src/nodes/rule_engine.py:298-391`
- Modify: `src/skills/loader.py` (添加注册分发)

- [ ] **Step 1: 在 SkillLoader 中添加注册分发逻辑**

在 `loader.py` 的 `load_all()` 末尾和 `reload()` 末尾调用注册：

```python
# src/skills/loader.py — 在 load_all() 的 return 前添加
    def _register_all(self) -> None:
        """将所有已加载 Skill 注册到各 Registry。"""
        from .registries import (
            TriggerRegistry, RoutingRegistry, TemplateRegistry,
            ToolRegistry, JudgmentRegistry, TestRegistry,
        )
        # 获取或创建全局 Registry 实例
        registries = get_registries()
        # 清空
        for reg in registries.values():
            reg.clear()
        # 注册
        for skill in self._registry.values():
            registries["trigger"].register(skill)
            registries["routing"].register(skill)
            registries["template"].register(skill)
            registries["tool"].register(skill)
            registries["judgment"].register(skill)
            registries["test"].register(skill)
        logger.info(f"[SkillLoader] Registered {len(self._registry)} skills to registries")
```

在文件末尾添加全局 Registry 管理：

```python
# src/skills/loader.py — 文件末尾

_registry_instances: Optional[dict] = None


def get_registries() -> dict:
    """获取全局 Registry 实例字典。"""
    global _registry_instances
    if _registry_instances is None:
        from .registries import (
            TriggerRegistry, RoutingRegistry, TemplateRegistry,
            ToolRegistry, JudgmentRegistry, TestRegistry,
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
```

- [ ] **Step 2: 改造 RuleEngine.match() 优先从 TriggerRegistry 读取**

```python
# src/nodes/rule_engine.py — 修改 RuleEngine.match() 方法

    @classmethod
    def match(cls, user_input: str) -> Optional[RuleMatch]:
        """
        Attempt rule matching. Returns RuleMatch on hit, None on miss.

        Priority: SkillLoader TriggerRegistry → legacy inline rules (fallback).
        """
        # 优先从 Skill 系统匹配
        try:
            from ..skills.loader import get_registries
            trigger_registry = get_registries()["trigger"]
            result = trigger_registry.match(user_input)
            if result:
                return RuleMatch(
                    intent=result["intent"],
                    params=result["params"],
                    confidence=result["confidence"],
                    template_id=result["template_id"],
                    fast_path_eligible=result["fast_path_eligible"],
                )
        except (ImportError, KeyError):
            pass  # Skill 系统未初始化，fallback 到内置规则

        # Fallback: 内置规则（渐进迁移期保留）
        text = user_input.strip()
        for rule, pattern in _COMPILED_RULES:
            m = pattern.search(text)
            if m:
                try:
                    params = rule["param_extract"](m)
                    return RuleMatch(
                        intent=rule["intent"],
                        params=params,
                        confidence=rule["confidence"],
                        template_id=rule["template"],
                        fast_path_eligible=rule["fast_path"],
                    )
                except (ValueError, IndexError, AttributeError):
                    continue
        return None
```

- [ ] **Step 3: 运行现有测试确认不破坏**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/ -v --timeout=30`
Expected: 现有测试全部通过（fallback 保证兼容）

- [ ] **Step 4: Commit**

```bash
git add src/skills/loader.py src/nodes/rule_engine.py
git commit -m "refactor(rule_engine): read from TriggerRegistry with legacy fallback"
```

---

### Task 5: route_by_intent 从 RoutingRegistry 读取

**Files:**
- Modify: `src/graph/routing.py:69-112`

- [ ] **Step 1: 改造 route_by_intent**

```python
# src/graph/routing.py — 替换 route_by_intent 函数

def route_by_intent(state: MainGraphState) -> str:
    """
    Route to appropriate sub-graph based on identified intent.

    Reads from RoutingRegistry (Skill system) with hardcoded fallback.
    """
    intent = state.get("intent", "chitchat")

    # 优先从 Skill 系统路由
    try:
        from ..skills.loader import get_registries
        group = get_registries()["routing"].resolve(intent)
        if group != "chitchat" or intent == "chitchat":
            return group
    except (ImportError, KeyError):
        pass  # Fallback

    # Fallback: 硬编码路由（渐进迁移期）
    data_intents = (
        "single_query", "spanloss_analysis", "color_diagnosis",
        "trend_analysis", "health_check", "spanloss_query",
        "connection_query", "performance_query", "fiber_alarm_query",
        "port_alarm_query", "colored_query", "stats_query", "trend_query",
    )
    if intent in data_intents:
        return "data_query"
    if intent == "batch_query":
        return "batch_query"
    if intent == "knowledge_qa":
        return "knowledge_qa"
    if intent == "report_generation":
        return "report"
    return "chitchat"
```

- [ ] **Step 2: 运行测试**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/graph/routing.py
git commit -m "refactor(routing): read from RoutingRegistry with fallback"
```

---

### Task 6: rule_judgment 委托给 JudgmentEngine

**Files:**
- Modify: `src/nodes/rule_judgment.py:25-130`

- [ ] **Step 1: 改造 rule_judgment_node**

```python
# src/nodes/rule_judgment.py — 替换 rule_judgment_node 函数

async def rule_judgment_node(state: MainGraphState) -> dict:
    """
    Programmatic judgment: generate structured conclusions from data.

    Delegates to JudgmentEngine (Skill system) with legacy fallback.
    """
    data_summary = state.get("collected_data_summary", "") or ""

    # 优先使用 Skill 系统的 JudgmentEngine
    try:
        from ..skills.loader import get_registries
        engine = get_registries()["judgment"].engine
        result = engine.evaluate(data_summary)
        if result["findings"]:  # 有匹配结果
            judgment = RuleJudgment(
                status=result["status"],
                findings=result["findings"],
                metrics=result["metrics"],
                suggested_actions=result["actions"],
            )
            logger.info(f"[RuleJudgment] (skill) status={result['status']}, findings={len(result['findings'])}")
            return {"rule_judgment": judgment.model_dump()}
    except (ImportError, KeyError):
        pass  # Fallback

    # Fallback: 原有 if-else 逻辑（渐进迁移期保留）
    return await _legacy_judgment(data_summary)


async def _legacy_judgment(data_summary: str) -> dict:
    """原有硬编码判断逻辑（迁移完成后删除）。"""
    findings: list[str] = []
    metrics: dict = {}
    status = "NORMAL"

    for line in data_summary.split("\n"):
        line_lower = line.lower()
        # ... (保留原有 if-else 链，此处省略重复代码)

    # 与原实现完全相同的逻辑
    suggested_actions: list[str] = []
    if status == "CRITICAL":
        suggested_actions = ["立即派单检修", "检查关联光纤是否受影响", "通知值班主管"]
    elif status == "WARNING":
        suggested_actions = ["列入下次巡检计划", "持续监控趋势变化"]
    if not findings:
        findings.append("未发现明显异常")

    judgment = RuleJudgment(status=status, findings=findings, metrics=metrics, suggested_actions=suggested_actions)
    return {"rule_judgment": judgment.model_dump()}
```

- [ ] **Step 2: 运行测试**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/nodes/rule_judgment.py
git commit -m "refactor(rule_judgment): delegate to JudgmentEngine with fallback"
```

---

## Phase 3: 全量迁移

### Task 7: 迁移 Fast Path Skills (10 个 YAML)

**Files:**
- Create: `skills/connection_query.yaml`
- Create: `skills/performance_query.yaml`
- Create: `skills/fiber_alarm_query.yaml`
- Create: `skills/port_alarm_query.yaml`
- Create: `skills/fiber_status_query.yaml`
- Create: `skills/board_query.yaml`
- Create: `skills/colored_query.yaml`
- Create: `skills/stats_query.yaml`
- Create: `skills/trend_query.yaml`
- Create: `skills/history_performance.yaml`

- [ ] **Step 1: 创建 connection_query.yaml**

```yaml
# skills/connection_query.yaml
id: connection_query
name: 光纤连纤查询
version: "1.0"
description: "查询光纤连接关系（跨网元纤链路）"

triggers:
  - pattern: "(?:查|看|查询)\\s*(?:光纤|FIB)[-_]?(\\d+)\\s*(?:的)?\\s*(?:连纤|连接|拓扑)"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0
  - pattern: "(?:分析|诊断|排查)?\\s*连纤\\s*(\\d+)\\s*(?:中断|断开|故障)?\\s*(?:的)?\\s*(?:原因|问题)?"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0

routing:
  intent: connection_query
  group: data_query
  fast_path_eligible: true
  template_id: T_CONNECTION

tools:
  - id: query_connection
    endpoint: "/api/v1/topology/fibers/{fiber_id}"
    method: GET
    timeout: 2.0
    params:
      fiber_id: "{fiber_id}"
    response_extract: {}

template:
  fast_path: "光纤 {fiber_id} 连纤信息：{data}"
  status_map: {}

collector_tools:
  - fiber_connection_query
  - fiber_scene_query

test_cases:
  - input: "查光纤 3 的连接"
    expected_intent: connection_query
    expected_params: { fiber_id: 3 }
    expected_fast_path: true
  - input: "连纤5中断的原因"
    expected_intent: connection_query
    expected_params: { fiber_id: 5 }
    expected_fast_path: true
```

- [ ] **Step 2: 创建其余 9 个 Fast Path YAML（按相同模式）**

每个文件遵循 `spanloss_query.yaml` 的结构，关键差异：

| 文件 | endpoint | template |
|------|----------|----------|
| `performance_query.yaml` | `/api/v1/fibers/{fiber_id}/performance` | `T_PERFORMANCE` |
| `fiber_alarm_query.yaml` | `/api/v1/topology/fibers/{fiber_id}` | `T_FIBER_ALARM` |
| `port_alarm_query.yaml` | `/api/v1/alarms/current?board_id=X&port_id=Y` | `T_PORT_ALARM` |
| `fiber_status_query.yaml` | `/api/v1/fibers/{fiber_id}/spanloss` | `T_FIBER_STATUS` |
| `board_query.yaml` | `/api/v1/boards/{board_id}` | `T_BOARD` |
| `colored_query.yaml` | `/api/v1/fibers/colored?color=X` | `T_COLORED` |
| `stats_query.yaml` | `/api/v1/fibers/stats` | `T_STATS` |
| `trend_query.yaml` | `/api/v1/fibers/stats/trend` | `T_TREND` |
| `history_performance.yaml` | `/api/v1/fibers/{fiber_id}/performance/history` | `T_PERFORMANCE` |

- [ ] **Step 3: 验证所有 YAML 可加载**

Run: `cd Agent/LangGraph-agent && python -c "from src.skills.loader import SkillLoader; from pathlib import Path; l = SkillLoader(Path('skills')); print(f'Loaded: {l.load_all()}')"`
Expected: `Loaded: 11` (含 spanloss_query)

- [ ] **Step 4: Commit**

```bash
git add skills/*.yaml
git commit -m "feat(skills): add 10 Fast Path skill YAML definitions"
```

---

### Task 8: 迁移 Normal Path Skills (6 个 YAML)

**Files:**
- Create: `skills/color_diagnosis.yaml`
- Create: `skills/spanloss_analysis.yaml`
- Create: `skills/health_check.yaml`
- Create: `skills/batch_query.yaml`
- Create: `skills/knowledge_qa.yaml`
- Create: `skills/report_generation.yaml`

- [ ] **Step 1: 创建 color_diagnosis.yaml**

```yaml
# skills/color_diagnosis.yaml
id: color_diagnosis
name: 光纤颜色诊断
version: "1.0"
description: "诊断光纤变红/变黄的原因（多步分析）"

triggers:
  - pattern: "(?:光纤|FIB)[-_]?(\\d+)\\s*(?:为什么|为何|怎么)\\s*(?:变)?(?:红|红色)"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0
  - pattern: "(?:光纤|FIB)[-_]?(\\d+)\\s*(?:为什么|为何|怎么)\\s*(?:变)?(?:黄|黄色)"
    params:
      fiber_id: { group: 1, type: int }
    confidence: 1.0

routing:
  intent: color_diagnosis
  group: data_query
  fast_path_eligible: false
  template_id: ""

tools: []

judgment:
  metric: color
  extract_pattern: "color[=:]\\s*(\\w+)"
  conditions:
    - op: "=="
      value: "RED"
      status: CRITICAL
      finding: "光纤颜色为红色（中断）"
  default:
    status: NORMAL
    finding: "光纤颜色正常"
  actions:
    CRITICAL: ["立即排查中断原因", "检查关联告警"]

collector_tools:
  - fiber_spanloss_query
  - fiber_performance_query
  - alarm_query
  - fiber_trend_query

test_cases:
  - input: "光纤 5 为什么变红了"
    expected_intent: color_diagnosis
    expected_params: { fiber_id: 5 }
    expected_fast_path: false
```

- [ ] **Step 2: 创建其余 5 个 Normal Path YAML**

| 文件 | intent | collector_tools |
|------|--------|----------------|
| `spanloss_analysis.yaml` | spanloss_analysis | spanloss + performance + alarm + trend |
| `health_check.yaml` | health_check | spanloss + performance + alarm + stats |
| `batch_query.yaml` | batch_query | batch_fiber_performance + batch_alarm |
| `knowledge_qa.yaml` | knowledge_qa | rag_query + rag_search |
| `report_generation.yaml` | report_generation | stats + performance + alarm + export |

- [ ] **Step 3: 验证全部 16+1 个 YAML 可加载**

Run: `cd Agent/LangGraph-agent && python -c "from src.skills.loader import SkillLoader; from pathlib import Path; l = SkillLoader(Path('skills')); print(f'Loaded: {l.load_all()}')"`
Expected: `Loaded: 17` (或 16，取决于是否合并)

- [ ] **Step 4: Commit**

```bash
git add skills/*.yaml
git commit -m "feat(skills): add 6 Normal Path skill YAML definitions"
```

---

### Task 9: 删除硬编码（清理）

**Files:**
- Modify: `src/nodes/rule_engine.py` — 删除 `RULES` 列表和 `_COMPILED_RULES`
- Modify: `src/nodes/fast_path_executor.py` — 删除 `_query_*` 函数，改用 ToolRegistry
- Modify: `src/nodes/rule_judgment.py` — 删除 `_legacy_judgment`

- [ ] **Step 1: 确认 Skill 系统完全覆盖**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills.py -v`
Expected: ALL PASS

- [ ] **Step 2: 从 rule_engine.py 删除 RULES 列表**

删除第 40-295 行的 `RULES` 列表和 `_COMPILED_RULES`，删除 `match()` 中的 fallback 分支。

- [ ] **Step 3: 从 fast_path_executor.py 删除 _query_* 函数**

替换 if-elif 链为 ToolRegistry 调用：

```python
# fast_path_executor_node 中的 API 调用改为：
from ..skills.loader import get_registries

tool_registry = get_registries()["tool"]
tools = tool_registry.get_tools(intent)
if tools:
    result = await _execute_tool(tools[0], params)
else:
    result = "未找到对应工具"
```

- [ ] **Step 4: 运行全部测试确认无回归**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/nodes/rule_engine.py src/nodes/fast_path_executor.py src/nodes/rule_judgment.py
git commit -m "refactor: remove hardcoded rules, delegate fully to Skill system"
```

---

## Phase 4: 热加载 + 自动测试

### Task 10: 热加载 API

**Files:**
- Modify: `src/server.py`

- [ ] **Step 1: 添加 Skill 管理端点**

```python
# src/server.py — 在现有路由后添加

@app.post("/api/v1/skills/reload")
async def reload_skills():
    """热加载 Skill：清空注册表 → 重新扫描 → 重新注册。"""
    from .skills.loader import get_skill_loader, SkillLoadError
    try:
        loader = get_skill_loader()
        count = loader.reload()
        loader._register_all()
        return {"status": "ok", "skills_loaded": count}
    except SkillLoadError as e:
        return JSONResponse(status_code=400, content={"status": "error", "errors": e.errors})


@app.get("/api/v1/skills")
async def list_skills():
    """列出所有已加载的 Skill。"""
    from .skills.loader import get_skill_loader
    loader = get_skill_loader()
    return {
        "skills": [
            {"id": s.id, "name": s.name, "version": s.version,
             "fast_path": s.routing.fast_path_eligible, "intent": s.routing.intent}
            for s in loader.all_skills()
        ]
    }
```

- [ ] **Step 2: 在 startup 中初始化 SkillLoader**

```python
# src/server.py — 在 lifespan/startup 中添加
from .skills.loader import get_skill_loader
skill_loader = get_skill_loader()
skill_loader._register_all()
logger.info(f"[Startup] Skill system initialized: {len(skill_loader.all_skills())} skills")
```

- [ ] **Step 3: 手动验证**

Run: 启动服务后 `curl -X POST http://localhost:8000/api/v1/skills/reload`
Expected: `{"status": "ok", "skills_loaded": 16}`

- [ ] **Step 4: Commit**

```bash
git add src/server.py
git commit -m "feat(server): add /api/v1/skills/reload and /api/v1/skills endpoints"
```

---

### Task 11: 自动回归测试

**Files:**
- Create: `tests/test_skills_auto.py`

- [ ] **Step 1: 实现自动参数化测试**

```python
# tests/test_skills_auto.py
"""从 Skill YAML 的 test_cases 字段自动生成回归测试。"""

import pytest
from pathlib import Path

from src.skills.loader import SkillLoader
from src.skills.registries import TriggerRegistry


# 加载所有 Skill
_skills_dir = Path(__file__).parent.parent / "skills"
_loader = SkillLoader(_skills_dir)
_loader.load_all()

# 构建 TriggerRegistry
_trigger_registry = TriggerRegistry()
for skill in _loader.all_skills():
    _trigger_registry.register(skill)

# 收集所有测试用例
_all_cases = [
    (skill.id, tc)
    for skill in _loader.all_skills()
    for tc in skill.test_cases
]


@pytest.mark.parametrize("skill_id,test_case", _all_cases, ids=[f"{sid}:{tc.input}" for sid, tc in _all_cases])
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
    assert result["fast_path_eligible"] == test_case.expected_fast_path


def test_all_skills_have_test_cases():
    """每个 Skill 应至少有一个测试用例。"""
    for skill in _loader.all_skills():
        assert len(skill.test_cases) >= 1, f"Skill '{skill.id}' 缺少 test_cases"


def test_skill_ids_unique():
    """所有 Skill ID 应唯一。"""
    ids = [s.id for s in _loader.all_skills()]
    assert len(ids) == len(set(ids)), f"重复的 Skill ID: {[x for x in ids if ids.count(x) > 1]}"
```

- [ ] **Step 2: 运行自动回归测试**

Run: `cd Agent/LangGraph-agent && python -m pytest tests/test_skills_auto.py -v`
Expected: ALL PASS（每个 YAML 的 test_cases 都通过）

- [ ] **Step 3: Commit**

```bash
git add tests/test_skills_auto.py
git commit -m "test(skills): add auto-generated regression tests from YAML test_cases"
```

---

## 验证清单

完成所有 Task 后，执行最终验证：

```bash
# 1. 全部测试通过
cd Agent/LangGraph-agent && python -m pytest tests/ -v --timeout=60

# 2. Skill 加载验证
python -c "from src.skills.loader import SkillLoader; from pathlib import Path; l = SkillLoader(Path('skills')); c = l.load_all(); print(f'Skills: {c}'); assert c >= 16"

# 3. 触发匹配验证
python -c "
from src.skills.loader import SkillLoader, get_registries
from pathlib import Path
l = SkillLoader(Path('skills'))
l.load_all()
l._register_all()
from src.skills.loader import get_registries
r = get_registries()['trigger']
assert r.match('查光纤3的衰耗') is not None
assert r.match('光纤5为什么变红') is not None
print('Trigger matching: OK')
"

# 4. 判断引擎验证
python -c "
from src.skills.judgment_engine import JudgmentEngine
from src.skills.schema import JudgmentCondition, JudgmentDefault
e = JudgmentEngine()
e.register_rule('spanloss', r'spanloss[=:]\s*([\d.]+)', [JudgmentCondition(op='>', value='8.0', status='CRITICAL', finding='超标')], JudgmentDefault(), {})
r = e.evaluate('spanloss=9.5')
assert r['status'] == 'CRITICAL'
print('JudgmentEngine: OK')
"
```
