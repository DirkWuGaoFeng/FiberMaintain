# 三层架构迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 v7.1 的 18 节点线性管道重构为 Lead Router + 三层能力 Agent（Collection / Analysis / Expression）架构，实现"YAML 定义做什么，Python 定义怎么做"的零代码扩展能力。

**Architecture:** Lead Router（规则优先 + LLM 兜底）读取 Skill YAML 生成 ExecutionPlan，分派给三个能力 Agent 执行。Collection ↔ Analysis 之间允许直接循环（≤3 轮）。Expression 负责格式化输出。旧图保留为 fallback，双模式共存过渡。

**Tech Stack:** Python 3.11+, LangGraph, Pydantic v2, PyYAML, pytest

---

## 架构总览

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Lead Router                                         │
│  1. InputGuard (复用现有)                            │
│  2. ScenarioResolver: YAML 规则匹配 → ExecutionPlan │
│  3. LLM 兜底分类 (仅规则未命中时)                    │
└───────────────────────┬─────────────────────────────┘
                        │ ExecutionPlan
                        ▼
┌─────────────────────────────────────────────────────┐
│  Orchestrator (循环控制器)                           │
│  ┌──────────────┐      ┌──────────────┐            │
│  │ Collection   │─────▶│  Analysis    │            │
│  │ Agent        │◀─────│  Agent       │            │
│  │ (数据获取)   │ loop │  (判断+推理) │            │
│  └──────────────┘ ≤3   └──────┬───────┘            │
│                                │                    │
│                                ▼                    │
│                       ┌──────────────┐              │
│                       │  Expression  │              │
│                       │  Agent       │              │
│                       │  (格式化)    │              │
│                       └──────────────┘              │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
                   Final Response
```

## 文件结构规划

```
src/
├── v8/                          # 新架构（独立目录，不影响 v7.1）
│   ├── __init__.py
│   ├── models.py                # ExecutionPlan, AgentResult, LoopContext
│   ├── lead_router.py           # Lead Router: 规则匹配 + LLM 兜底
│   ├── orchestrator.py          # 循环控制器
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseAgent 抽象类
│   │   ├── collection_agent.py  # 数据采集 Agent
│   │   ├── analysis_agent.py    # 分析判断 Agent
│   │   └── expression_agent.py  # 表达输出 Agent
│   └── graph.py                 # v8 LangGraph 图定义（双模式入口）
├── graph/                       # v7.1 旧图（保留不动）
│   ├── main_graph.py
│   └── ...
```

---

### Task 1: 数据模型 — ExecutionPlan 与 AgentResult

**Files:**
- Create: `src/v8/__init__.py`
- Create: `src/v8/models.py`
- Test: `tests/unit/test_v8_models.py`

- [ ] **Step 1: 创建 v8 包和数据模型**

```python
# src/v8/__init__.py
"""v8 三层能力架构 — Lead Router + Collection/Analysis/Expression."""
```

```python
# src/v8/models.py
"""
v8 核心数据模型.

ExecutionPlan: Lead Router 的输出，驱动三层 Agent 执行
AgentResult: 每个 Agent 的统一返回格式
LoopContext: Collection ↔ Analysis 循环上下文
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentLayer(str, Enum):
    """三层能力 Agent 标识."""
    COLLECTION = "collection"
    ANALYSIS = "analysis"
    EXPRESSION = "expression"


class ExecutionPlan(BaseModel):
    """
    Lead Router 输出的执行计划.

    由 Skill YAML 的 routing + tools + judgment 字段解析而来。
    驱动 Orchestrator 分派任务给三层 Agent。
    """
    # 场景标识
    scenario_id: str = ""
    intent: str = ""
    confidence: float = 0.0
    match_type: str = "rule"  # "rule" | "llm" | "default"

    # Collection Agent 指令
    tools: list[str] = Field(default_factory=list)
    tool_params_hint: dict[str, Any] = Field(default_factory=dict)

    # Analysis Agent 指令
    judgment_rules: list[str] = Field(default_factory=list)
    threshold_refs: list[str] = Field(default_factory=list)
    analysis_mode: str = "rule_first"  # "rule_first" | "llm_only" | "rule_only"

    # Expression Agent 指令
    output_format: str = "narrative"  # "narrative" | "table" | "report" | "raw"
    output_template: str = ""

    # 循环控制
    max_loop_rounds: int = 3

    # 原始 Skill 元数据（透传）
    skill_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """每个 Agent 的统一返回格式."""
    layer: AgentLayer
    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    # 循环信号
    needs_more_data: bool = False
    additional_query: Optional[dict[str, Any]] = None
    # 度量
    llm_calls: int = 0
    latency_ms: float = 0.0


class LoopContext(BaseModel):
    """Collection ↔ Analysis 循环上下文."""
    round: int = 0
    max_rounds: int = 3
    collection_results: list[dict[str, Any]] = Field(default_factory=list)
    analysis_verdicts: list[dict[str, Any]] = Field(default_factory=list)
    terminated_reason: str = ""  # "complete" | "max_rounds" | "no_progress"


class V8State(BaseModel):
    """v8 图的顶层状态."""
    # 输入
    user_input: str = ""
    trace_id: str = ""
    session_id: str = ""

    # Lead Router 输出
    execution_plan: Optional[ExecutionPlan] = None
    normalized_params: dict[str, Any] = Field(default_factory=dict)

    # 循环上下文
    loop_context: LoopContext = Field(default_factory=LoopContext)

    # 各 Agent 最新结果
    collection_result: Optional[AgentResult] = None
    analysis_result: Optional[AgentResult] = None
    expression_result: Optional[AgentResult] = None

    # 最终输出
    final_response: str = ""
    final_status: str = ""

    # 治理
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
    total_llm_calls: int = 0
```

- [ ] **Step 2: 编写模型测试**

```python
# tests/unit/test_v8_models.py
"""v8 数据模型单元测试."""
import pytest
from src.v8.models import (
    AgentLayer, AgentResult, ExecutionPlan, LoopContext, V8State,
)


class TestExecutionPlan:
    def test_default_values(self):
        plan = ExecutionPlan()
        assert plan.max_loop_rounds == 3
        assert plan.analysis_mode == "rule_first"
        assert plan.tools == []

    def test_from_skill_yaml_fields(self):
        plan = ExecutionPlan(
            scenario_id="spanloss_check",
            intent="spanloss_check",
            confidence=0.95,
            match_type="rule",
            tools=["fiber_spanloss_query", "fiber_connection_query"],
            judgment_rules=["spanloss_threshold"],
            threshold_refs=["default_spanloss"],
            output_format="narrative",
        )
        assert len(plan.tools) == 2
        assert plan.threshold_refs == ["default_spanloss"]

    def test_serialization_roundtrip(self):
        plan = ExecutionPlan(scenario_id="test", tools=["a", "b"])
        data = plan.model_dump()
        restored = ExecutionPlan.model_validate(data)
        assert restored == plan


class TestAgentResult:
    def test_success_result(self):
        r = AgentResult(layer=AgentLayer.COLLECTION, data={"fibers": [1, 2]})
        assert r.success
        assert not r.needs_more_data

    def test_needs_more_data_signal(self):
        r = AgentResult(
            layer=AgentLayer.ANALYSIS,
            needs_more_data=True,
            additional_query={"tool": "alarm_query", "params": {"fiber_id": 1}},
        )
        assert r.needs_more_data
        assert r.additional_query["tool"] == "alarm_query"


class TestLoopContext:
    def test_initial_state(self):
        ctx = LoopContext(max_rounds=3)
        assert ctx.round == 0
        assert ctx.terminated_reason == ""

    def test_termination(self):
        ctx = LoopContext(round=3, max_rounds=3, terminated_reason="max_rounds")
        assert ctx.round >= ctx.max_rounds


class TestV8State:
    def test_full_lifecycle(self):
        state = V8State(user_input="查看光纤1", trace_id="t-001")
        state.execution_plan = ExecutionPlan(scenario_id="spanloss_check")
        state.collection_result = AgentResult(
            layer=AgentLayer.COLLECTION, data={"spanloss": 3.2}
        )
        assert state.execution_plan.scenario_id == "spanloss_check"
        assert state.collection_result.data["spanloss"] == 3.2
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_models.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/ tests/unit/test_v8_models.py
git commit -m "feat(v8): add core data models — ExecutionPlan, AgentResult, LoopContext"
```

---

### Task 2: BaseAgent 抽象类

**Files:**
- Create: `src/v8/agents/__init__.py`
- Create: `src/v8/agents/base.py`
- Test: `tests/unit/test_v8_base_agent.py`

- [ ] **Step 1: 创建 BaseAgent**

```python
# src/v8/agents/__init__.py
"""v8 三层能力 Agent."""
from .base import BaseAgent

__all__ = ["BaseAgent"]
```

```python
# src/v8/agents/base.py
"""
BaseAgent — 三层 Agent 的统一抽象.

每个 Agent:
- 接收 ExecutionPlan + 上下文
- 执行自己的职责
- 返回 AgentResult
- 记录 audit_trail
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from ..models import AgentLayer, AgentResult, ExecutionPlan

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """三层 Agent 基类."""

    @property
    @abstractmethod
    def layer(self) -> AgentLayer:
        """Agent 所属层."""
        ...

    @abstractmethod
    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        """
        执行 Agent 职责.

        Args:
            plan: Lead Router 生成的执行计划
            context: 运行时上下文（user_input, normalized_params, 前序 Agent 结果等）

        Returns:
            AgentResult 统一格式
        """
        ...

    async def run(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        """带计时和异常兜底的执行入口."""
        trace_id = context.get("trace_id", "")
        start = time.time()
        logger.info(f"[TRACE:{trace_id}] [{self.layer.value}_agent] START")

        try:
            result = await self.execute(plan, context)
            result.latency_ms = round((time.time() - start) * 1000, 2)
            logger.info(
                f"[TRACE:{trace_id}] [{self.layer.value}_agent] "
                f"OK {result.latency_ms}ms success={result.success}"
            )
            return result
        except Exception as e:
            elapsed = round((time.time() - start) * 1000, 2)
            logger.error(
                f"[TRACE:{trace_id}] [{self.layer.value}_agent] "
                f"ERROR {elapsed}ms error={e}"
            )
            return AgentResult(
                layer=self.layer,
                success=False,
                error=str(e),
                latency_ms=elapsed,
            )
```

- [ ] **Step 2: 编写测试**

```python
# tests/unit/test_v8_base_agent.py
"""BaseAgent 抽象类测试."""
import pytest
from src.v8.agents.base import BaseAgent
from src.v8.models import AgentLayer, AgentResult, ExecutionPlan


class MockAgent(BaseAgent):
    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.COLLECTION

    async def execute(self, plan, context):
        if context.get("should_fail"):
            raise ValueError("模拟失败")
        return AgentResult(layer=self.layer, data={"ok": True})


class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_run_success(self):
        agent = MockAgent()
        plan = ExecutionPlan(scenario_id="test")
        result = await agent.run(plan, {"trace_id": "t1"})
        assert result.success
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_run_catches_exception(self):
        agent = MockAgent()
        plan = ExecutionPlan()
        result = await agent.run(plan, {"trace_id": "t1", "should_fail": True})
        assert not result.success
        assert "模拟失败" in result.error

    @pytest.mark.asyncio
    async def test_layer_property(self):
        agent = MockAgent()
        assert agent.layer == AgentLayer.COLLECTION
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_base_agent.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/agents/ tests/unit/test_v8_base_agent.py
git commit -m "feat(v8): add BaseAgent abstract class with timing and error handling"
```

---

### Task 3: Collection Agent

**Files:**
- Create: `src/v8/agents/collection_agent.py`
- Test: `tests/unit/test_v8_collection_agent.py`

- [ ] **Step 1: 实现 Collection Agent**

```python
# src/v8/agents/collection_agent.py
"""
Collection Agent — 数据采集层.

职责：根据 ExecutionPlan.tools 调用后端 API 获取数据。
约束：
- 只使用 plan.tools 中声明的工具（Bounded ReAct）
- 不做分析判断
- 返回结构化原始数据
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ...config import MAX_LOOPS
from ...llm.provider import get_data_collector_llm
from ...tools import DATA_COLLECTOR_TOOLS
from ..models import AgentLayer, AgentResult, ExecutionPlan
from .base import BaseAgent

logger = logging.getLogger(__name__)

# 工具名 → 工具对象 的映射
_TOOL_MAP = {t.name: t for t in DATA_COLLECTOR_TOOLS}

COLLECTION_SYSTEM = """你是光纤维护系统的数据采集员。
你的唯一职责是调用工具获取光纤数据，不做分析判断。

## 规则
1. 只使用指定的工具列表中的工具
2. 光纤 ID 为整数，直接使用
3. 获取所有相关数据
4. 如果某个查询失败，报告错误但继续其他查询
5. 最终输出 JSON 格式的数据摘要
6. 不要编造数据，不要做分析判断

## 可用工具
{tools_list}

## 输出格式
{{"collected": [{{"tool": "工具名", "params": {{}}, "result_summary": "关键数据"}}], "errors": [...]}}
"""


class CollectionAgent(BaseAgent):
    """数据采集 Agent — Bounded ReAct."""

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.COLLECTION

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        from langgraph.prebuilt import create_react_agent

        trace_id = context.get("trace_id", "")

        # Bounded: 只使用 plan 声明的工具
        allowed_tools = self._resolve_tools(plan.tools)
        if not allowed_tools:
            allowed_tools = DATA_COLLECTOR_TOOLS  # fallback 全量

        # 构建 prompt
        prompt = self._build_prompt(plan, context)
        tools_list = ", ".join(t.name for t in allowed_tools)
        system = COLLECTION_SYSTEM.format(tools_list=tools_list)

        # ReAct Agent
        llm = get_data_collector_llm()
        agent = create_react_agent(
            model=llm,
            tools=allowed_tools,
            prompt=system,
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 10},
        )

        # 提取结果
        messages = result.get("messages", [])
        data_summary = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                data_summary = msg.content
                break

        if not data_summary:
            return AgentResult(
                layer=self.layer,
                success=False,
                error="数据采集未返回有效结果",
            )

        # 截断保护
        if len(data_summary) > 3000:
            data_summary = data_summary[:3000] + "\n...(截断)"

        return AgentResult(
            layer=self.layer,
            success=True,
            data={"raw_summary": data_summary, "tools_used": plan.tools},
            llm_calls=1,
        )

    def _resolve_tools(self, tool_names: list[str]) -> list:
        """将工具名列表解析为工具对象."""
        resolved = []
        for name in tool_names:
            if name in _TOOL_MAP:
                resolved.append(_TOOL_MAP[name])
            else:
                logger.warning(f"[CollectionAgent] Unknown tool: {name}")
        return resolved

    def _build_prompt(self, plan: ExecutionPlan, context: dict) -> str:
        """构建采集 prompt."""
        parts = []

        # 补充采集信号
        additional = context.get("additional_query")
        if additional:
            parts.append(f"## 补充采集（第 {context.get('loop_round', 1)} 轮）")
            parts.append(f"原因：{additional.get('reason', '')}")
            if additional.get("tool"):
                parts.append(f"建议工具：{additional['tool']}")

        # 用户请求
        user_input = context.get("user_input", "")
        if user_input:
            parts.append(f"## 用户请求\n{user_input}")

        # 参数
        params = context.get("normalized_params", {})
        if params:
            parts.append(f"## 参数\n{json.dumps(params, ensure_ascii=False)}")

        parts.append("\n请调用工具获取数据。")
        return "\n\n".join(parts)
```

- [ ] **Step 2: 编写测试（mock LLM）**

```python
# tests/unit/test_v8_collection_agent.py
"""Collection Agent 单元测试."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.v8.agents.collection_agent import CollectionAgent
from src.v8.models import AgentLayer, ExecutionPlan


class TestCollectionAgent:
    def test_layer(self):
        agent = CollectionAgent()
        assert agent.layer == AgentLayer.COLLECTION

    def test_resolve_tools_valid(self):
        agent = CollectionAgent()
        tools = agent._resolve_tools(["fiber_spanloss_query", "alarm_query"])
        assert len(tools) == 2

    def test_resolve_tools_unknown(self):
        agent = CollectionAgent()
        tools = agent._resolve_tools(["nonexistent_tool"])
        assert len(tools) == 0

    def test_build_prompt_basic(self):
        agent = CollectionAgent()
        plan = ExecutionPlan(tools=["fiber_spanloss_query"])
        ctx = {"user_input": "查看光纤1", "normalized_params": {"fiber_ids": [1]}}
        prompt = agent._build_prompt(plan, ctx)
        assert "查看光纤1" in prompt
        assert "fiber_ids" in prompt

    def test_build_prompt_with_additional_query(self):
        agent = CollectionAgent()
        plan = ExecutionPlan()
        ctx = {
            "user_input": "查看光纤1",
            "additional_query": {"reason": "缺少告警数据", "tool": "alarm_query"},
            "loop_round": 2,
        }
        prompt = agent._build_prompt(plan, ctx)
        assert "补充采集" in prompt
        assert "alarm_query" in prompt
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_collection_agent.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/agents/collection_agent.py tests/unit/test_v8_collection_agent.py
git commit -m "feat(v8): implement CollectionAgent with Bounded ReAct"
```

---

### Task 4: Analysis Agent

**Files:**
- Create: `src/v8/agents/analysis_agent.py`
- Test: `tests/unit/test_v8_analysis_agent.py`

- [ ] **Step 1: 实现 Analysis Agent**

```python
# src/v8/agents/analysis_agent.py
"""
Analysis Agent — 分析判断层.

职责：
1. 规则判断（ThresholdEngine）— 确定性结论
2. LLM 深度分析 — 仅当规则无法覆盖时
3. 决定是否追加采集（needs_more_data 信号）

约束：
- 规则优先：能用规则判断的不调 LLM
- 阈值从 ThresholdEngine 获取
- 输出结构化 verdict
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ...governance.threshold_engine import get_threshold_engine
from ..models import AgentLayer, AgentResult, ExecutionPlan
from .base import BaseAgent

logger = logging.getLogger(__name__)


class AnalysisAgent(BaseAgent):
    """分析判断 Agent — 规则优先 + LLM 兜底."""

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.ANALYSIS

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        trace_id = context.get("trace_id", "")
        collection_data = context.get("collection_data", {})
        raw_summary = collection_data.get("raw_summary", "")

        # Phase 1: 规则判断
        rule_result = self._rule_judgment(raw_summary, plan)

        # 规则已给出明确结论 → 直接返回
        if rule_result["status"] != "UNKNOWN" and plan.analysis_mode != "llm_only":
            return AgentResult(
                layer=self.layer,
                success=True,
                data={
                    "verdict": rule_result,
                    "analysis_mode": "rule",
                    "narration_points": rule_result.get("findings", []),
                },
            )

        # Phase 2: LLM 深度分析（规则无法覆盖）
        llm_result = await self._llm_analysis(raw_summary, plan, context)
        return llm_result

    def _rule_judgment(self, raw_summary: str, plan: ExecutionPlan) -> dict[str, Any]:
        """程序化规则判断."""
        engine = get_threshold_engine()
        findings = []
        status = "NORMAL"

        # 提取 spanloss
        spanloss_matches = re.findall(
            r'(?:spanloss|跨段损耗|衰耗)[^\d]*?([\d.]+)\s*dB',
            raw_summary, re.IGNORECASE,
        )
        for val_str in spanloss_matches:
            val = float(val_str)
            jr = engine.judge_spanloss(val)
            findings.append(f"跨段损耗 {val}dB → {jr.level}")
            if jr.level == "CRITICAL":
                status = "CRITICAL"
            elif jr.level == "WARNING" and status != "CRITICAL":
                status = "WARNING"

        # 提取 OOP
        oop_matches = re.findall(
            r'(?:OOP|出光功率)[^\d-]*?(-?[\d.]+)\s*dBm',
            raw_summary, re.IGNORECASE,
        )
        for val_str in oop_matches:
            val = float(val_str)
            level = engine.judge_oop(val)
            if level != "NORMAL":
                findings.append(f"出光功率 {val}dBm → {level}")
                if level == "CRITICAL":
                    status = "CRITICAL"
                elif status != "CRITICAL":
                    status = "WARNING"

        if not findings:
            return {"status": "UNKNOWN", "findings": [], "metrics": {}}

        return {
            "status": status,
            "findings": findings,
            "metrics": {"spanloss": spanloss_matches, "oop": oop_matches},
        }

    async def _llm_analysis(
        self, raw_summary: str, plan: ExecutionPlan, context: dict
    ) -> AgentResult:
        """LLM 深度分析（规则无法覆盖时）."""
        from ...llm.provider import get_analysis_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            llm = get_analysis_llm()
            system = (
                "你是光纤维护专家。分析数据并给出结论。\n"
                "输出 JSON：{\"status\": \"NORMAL|WARNING|CRITICAL\", "
                "\"findings\": [...], \"suggestion\": \"...\", "
                "\"needs_more_data\": false, \"additional_query\": null}\n"
                "如果数据不足以判断，设 needs_more_data=true 并说明需要什么数据。"
            )
            user_msg = f"## 数据\n{raw_summary}\n\n## 用户问题\n{context.get('user_input', '')}"

            response = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user_msg),
            ])

            # 解析 JSON
            content = response.content if hasattr(response, "content") else str(response)
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                verdict = json.loads(json_match.group())
            else:
                verdict = {"status": "UNKNOWN", "findings": [content[:200]]}

            return AgentResult(
                layer=self.layer,
                success=True,
                data={"verdict": verdict, "analysis_mode": "llm"},
                needs_more_data=verdict.get("needs_more_data", False),
                additional_query=verdict.get("additional_query"),
                llm_calls=1,
            )
        except Exception as e:
            logger.error(f"[AnalysisAgent] LLM analysis failed: {e}")
            return AgentResult(
                layer=self.layer,
                success=False,
                error=f"LLM 分析失败: {e}",
                data={"verdict": {"status": "UNKNOWN", "findings": []}},
            )
```

- [ ] **Step 2: 编写测试**

```python
# tests/unit/test_v8_analysis_agent.py
"""Analysis Agent 单元测试."""
import pytest
from src.v8.agents.analysis_agent import AnalysisAgent
from src.v8.models import AgentLayer, ExecutionPlan


class TestAnalysisAgent:
    def test_layer(self):
        agent = AnalysisAgent()
        assert agent.layer == AgentLayer.ANALYSIS

    def test_rule_judgment_normal(self):
        agent = AnalysisAgent()
        plan = ExecutionPlan(judgment_rules=["spanloss_threshold"])
        result = agent._rule_judgment("跨段损耗 2.5 dB 正常", plan)
        assert result["status"] == "NORMAL"

    def test_rule_judgment_warning(self):
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        result = agent._rule_judgment("spanloss 为 5.5 dB", plan)
        assert result["status"] in ("WARNING", "CRITICAL")
        assert len(result["findings"]) > 0

    def test_rule_judgment_critical(self):
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        result = agent._rule_judgment("跨段损耗 9.0 dB", plan)
        assert result["status"] == "CRITICAL"

    def test_rule_judgment_oop_abnormal(self):
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        result = agent._rule_judgment("OOP 为 -12.5 dBm", plan)
        assert result["status"] != "NORMAL"

    def test_rule_judgment_no_data(self):
        agent = AnalysisAgent()
        plan = ExecutionPlan()
        result = agent._rule_judgment("没有相关数据", plan)
        assert result["status"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_execute_rule_first_mode(self):
        agent = AnalysisAgent()
        plan = ExecutionPlan(analysis_mode="rule_first")
        ctx = {
            "trace_id": "t1",
            "collection_data": {"raw_summary": "跨段损耗 3.0 dB"},
            "user_input": "查看光纤1",
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data["analysis_mode"] == "rule"
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_analysis_agent.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/agents/analysis_agent.py tests/unit/test_v8_analysis_agent.py
git commit -m "feat(v8): implement AnalysisAgent with rule-first + LLM fallback"
```

---

### Task 5: Expression Agent

**Files:**
- Create: `src/v8/agents/expression_agent.py`
- Test: `tests/unit/test_v8_expression_agent.py`

- [ ] **Step 1: 实现 Expression Agent**

```python
# src/v8/agents/expression_agent.py
"""
Expression Agent — 表达输出层.

职责：
- 将 Analysis verdict 格式化为用户友好的输出
- 支持多种输出格式：narrative / table / report / raw
- 数字模板填充（反幻觉）
- 不调用后端工具，不修改结论
"""
from __future__ import annotations

import logging
from typing import Any

from ...governance.number_validator import fill_template, validate_narration_numbers
from ..models import AgentLayer, AgentResult, ExecutionPlan
from .base import BaseAgent

logger = logging.getLogger(__name__)

# 状态 emoji 映射
_STATUS_EMOJI = {
    "NORMAL": "✅",
    "WARNING": "⚠️",
    "CRITICAL": "🚨",
    "UNKNOWN": "❓",
}


class ExpressionAgent(BaseAgent):
    """表达输出 Agent — 格式化 + 反幻觉."""

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.EXPRESSION

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        analysis_data = context.get("analysis_data", {})
        verdict = analysis_data.get("verdict", {})
        status = verdict.get("status", "UNKNOWN")
        findings = verdict.get("findings", [])
        suggestion = verdict.get("suggestion", "")

        # 根据 output_format 选择渲染方式
        fmt = plan.output_format
        if fmt == "raw":
            output = self._render_raw(verdict)
        elif fmt == "table":
            output = self._render_table(status, findings)
        else:
            output = self._render_narrative(status, findings, suggestion)

        # 反幻觉校验
        metrics = verdict.get("metrics", {})
        errors = validate_narration_numbers(output, metrics)
        if errors:
            logger.warning(f"[ExpressionAgent] Hallucination detected: {errors}")
            # 降级到纯模板
            output = self._render_narrative(status, findings, suggestion)

        return AgentResult(
            layer=self.layer,
            success=True,
            data={"response": output, "format": fmt},
        )

    def _render_narrative(
        self, status: str, findings: list[str], suggestion: str
    ) -> str:
        """叙述式输出."""
        emoji = _STATUS_EMOJI.get(status, "❓")
        lines = [f"{emoji} 光纤状态：{status}"]
        if findings:
            lines.append("")
            for f in findings:
                lines.append(f"  • {f}")
        if suggestion:
            lines.append(f"\n💡 建议：{suggestion}")
        return "\n".join(lines)

    def _render_table(self, status: str, findings: list[str]) -> str:
        """表格式输出."""
        lines = [f"| 状态 | {status} |", "|---|---|"]
        for i, f in enumerate(findings, 1):
            lines.append(f"| 发现{i} | {f} |")
        return "\n".join(lines)

    def _render_raw(self, verdict: dict) -> str:
        """原始 JSON 输出."""
        import json
        return json.dumps(verdict, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: 编写测试**

```python
# tests/unit/test_v8_expression_agent.py
"""Expression Agent 单元测试."""
import pytest
from src.v8.agents.expression_agent import ExpressionAgent
from src.v8.models import AgentLayer, ExecutionPlan


class TestExpressionAgent:
    def test_layer(self):
        agent = ExpressionAgent()
        assert agent.layer == AgentLayer.EXPRESSION

    @pytest.mark.asyncio
    async def test_narrative_normal(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {
                "verdict": {"status": "NORMAL", "findings": ["跨段损耗 2.5dB → NORMAL"]}
            }
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert "✅" in result.data["response"]
        assert "NORMAL" in result.data["response"]

    @pytest.mark.asyncio
    async def test_narrative_critical(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {
                "verdict": {
                    "status": "CRITICAL",
                    "findings": ["跨段损耗 9.0dB → CRITICAL"],
                    "suggestion": "立即安排现场检修",
                }
            }
        }
        result = await agent.execute(plan, ctx)
        assert "🚨" in result.data["response"]
        assert "建议" in result.data["response"]

    @pytest.mark.asyncio
    async def test_table_format(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="table")
        ctx = {"analysis_data": {"verdict": {"status": "WARNING", "findings": ["OOP异常"]}}}
        result = await agent.execute(plan, ctx)
        assert "|" in result.data["response"]

    @pytest.mark.asyncio
    async def test_raw_format(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="raw")
        ctx = {"analysis_data": {"verdict": {"status": "NORMAL", "findings": []}}}
        result = await agent.execute(plan, ctx)
        assert '"status"' in result.data["response"]
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_expression_agent.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/agents/expression_agent.py tests/unit/test_v8_expression_agent.py
git commit -m "feat(v8): implement ExpressionAgent with narrative/table/raw formats"
```

---

### Task 6: Lead Router — ScenarioResolver

**Files:**
- Create: `src/v8/lead_router.py`
- Test: `tests/unit/test_v8_lead_router.py`

- [ ] **Step 1: 实现 Lead Router**

```python
# src/v8/lead_router.py
"""
Lead Router — 场景解析与任务分派.

策略：规则优先 + LLM 兜底
1. 遍历已加载的 Skill YAML trigger 规则 → 精确匹配
2. 未命中 → 3b LLM 分类
3. 仍未命中 → default_skill 兜底

输出：ExecutionPlan（驱动三层 Agent）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..skills.loader import get_skill_loader, get_registries
from .models import ExecutionPlan

logger = logging.getLogger(__name__)


class LeadRouter:
    """场景解析器 — 规则优先 + LLM 兜底."""

    def __init__(self):
        self._loader = get_skill_loader()
        registries = get_registries()
        self._trigger_registry = registries["trigger"]
        self._routing_registry = registries["routing"]

    async def resolve(
        self,
        user_input: str,
        normalized_params: dict[str, Any],
        trace_id: str = "",
    ) -> ExecutionPlan:
        """
        解析用户输入 → 生成 ExecutionPlan.

        优先级：
        1. Skill YAML trigger 规则匹配
        2. LLM 意图分类（3b）
        3. default_skill 兜底
        """
        # Phase 1: 规则匹配
        plan = self._rule_match(user_input, normalized_params)
        if plan:
            logger.info(
                f"[TRACE:{trace_id}] [LeadRouter] Rule match: "
                f"scenario={plan.scenario_id} confidence={plan.confidence}"
            )
            return plan

        # Phase 2: LLM 分类
        plan = await self._llm_classify(user_input, trace_id)
        if plan:
            logger.info(
                f"[TRACE:{trace_id}] [LeadRouter] LLM classify: "
                f"scenario={plan.scenario_id} confidence={plan.confidence}"
            )
            return plan

        # Phase 3: 兜底
        logger.info(f"[TRACE:{trace_id}] [LeadRouter] Fallback to default")
        return self._default_plan(user_input)

    def _rule_match(
        self, user_input: str, params: dict[str, Any]
    ) -> Optional[ExecutionPlan]:
        """Skill YAML trigger 规则匹配."""
        match = self._trigger_registry.match(user_input)
        if not match:
            return None

        intent = match["intent"]
        skill = self._loader.get_skill(intent)
        if not skill:
            # 通过 intent 反查 skill
            for s in self._loader.all_skills():
                if s.routing.intent == intent:
                    skill = s
                    break
        if not skill:
            return None

        return ExecutionPlan(
            scenario_id=skill.id,
            intent=intent,
            confidence=match["confidence"],
            match_type="rule",
            tools=skill.collector_tools,
            judgment_rules=[skill.judgment.metric] if skill.judgment else [],
            threshold_refs=[],
            output_format="narrative",
            output_template=skill.template.fast_path if skill.template else "",
            max_loop_rounds=3,
            skill_metadata={"skill_id": skill.id, "version": skill.version},
        )

    async def _llm_classify(
        self, user_input: str, trace_id: str
    ) -> Optional[ExecutionPlan]:
        """LLM 意图分类（3b 轻量模型）."""
        try:
            from ..llm.provider import get_intent_llm
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = get_intent_llm()
            skills = self._loader.all_skills()
            skill_list = "\n".join(f"- {s.id}: {s.description}" for s in skills)

            system = (
                "你是意图分类器。根据用户输入选择最匹配的场景。\n"
                f"可选场景：\n{skill_list}\n\n"
                "只输出场景 ID，不要解释。如果没有匹配的，输出 UNKNOWN。"
            )

            response = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user_input),
            ])

            intent = response.content.strip().lower() if hasattr(response, "content") else ""
            if intent and intent != "unknown":
                skill = self._loader.get_skill(intent)
                if skill:
                    return ExecutionPlan(
                        scenario_id=skill.id,
                        intent=skill.routing.intent,
                        confidence=0.7,
                        match_type="llm",
                        tools=skill.collector_tools,
                        judgment_rules=[skill.judgment.metric] if skill.judgment else [],
                        threshold_refs=[],
                        output_format="narrative",
                        max_loop_rounds=3,
                    )
        except Exception as e:
            logger.warning(f"[TRACE:{trace_id}] [LeadRouter] LLM classify failed: {e}")

        return None

    def _default_plan(self, user_input: str) -> ExecutionPlan:
        """兜底计划."""
        # 尝试找 group='chitchat' 的 skill 作为默认
        for skill in self._loader.all_skills():
            if skill.routing.group == "chitchat":
                return ExecutionPlan(
                    scenario_id=skill.id,
                    intent=skill.routing.intent,
                    confidence=0.3,
                    match_type="default",
                    tools=skill.collector_tools,
                    output_format="narrative",
                    max_loop_rounds=3,
                )

        return ExecutionPlan(
            scenario_id="fallback",
            intent="general_query",
            confidence=0.1,
            match_type="default",
            tools=["fiber_connection_query", "fiber_performance_query", "alarm_query"],
            output_format="narrative",
        )
```

- [ ] **Step 2: 编写测试**

```python
# tests/unit/test_v8_lead_router.py
"""Lead Router 单元测试."""
import pytest
from unittest.mock import patch, AsyncMock
from src.v8.lead_router import LeadRouter
from src.v8.models import ExecutionPlan


class TestLeadRouter:
    def test_init(self):
        router = LeadRouter()
        assert router._loader is not None
        assert router._trigger_registry is not None

    @pytest.mark.asyncio
    async def test_resolve_rule_match(self):
        """规则命中 → 直接返回 plan."""
        router = LeadRouter()
        # "查看光纤1的跨段损耗" 应命中 spanloss_check skill
        plan = await router.resolve(
            "查看光纤1的跨段损耗",
            {"fiber_ids": [1]},
            trace_id="t1",
        )
        assert isinstance(plan, ExecutionPlan)
        assert plan.confidence > 0
        assert plan.match_type in ("rule", "llm", "default")

    @pytest.mark.asyncio
    async def test_resolve_fallback(self):
        """完全无法匹配 → 兜底 plan."""
        router = LeadRouter()
        plan = await router.resolve(
            "今天天气怎么样",
            {},
            trace_id="t2",
        )
        assert isinstance(plan, ExecutionPlan)
        assert plan.match_type in ("default", "llm")

    def test_default_plan(self):
        router = LeadRouter()
        plan = router._default_plan("随便问问")
        assert plan.scenario_id != ""
        assert len(plan.tools) > 0
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_lead_router.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/lead_router.py tests/unit/test_v8_lead_router.py
git commit -m "feat(v8): implement LeadRouter with rule-first + LLM fallback"
```

---

### Task 7: Orchestrator — 循环控制器

**Files:**
- Create: `src/v8/orchestrator.py`
- Test: `tests/unit/test_v8_orchestrator.py`

- [ ] **Step 1: 实现 Orchestrator**

```python
# src/v8/orchestrator.py
"""
Orchestrator — 三层 Agent 循环控制器.

职责：
1. 接收 ExecutionPlan
2. 分派 Collection → Analysis（循环 ≤ N 轮）
3. Analysis 完成后分派 Expression
4. 返回最终结果

循环终止条件：
- Analysis 判定完成（needs_more_data=False）
- 达到 max_loop_rounds
- 无进展检测（数据签名不变）
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from .agents.analysis_agent import AnalysisAgent
from .agents.collection_agent import CollectionAgent
from .agents.expression_agent import ExpressionAgent
from .models import AgentResult, ExecutionPlan, LoopContext, V8State

logger = logging.getLogger(__name__)


class Orchestrator:
    """三层 Agent 循环控制器."""

    def __init__(self):
        self.collection_agent = CollectionAgent()
        self.analysis_agent = AnalysisAgent()
        self.expression_agent = ExpressionAgent()

    async def execute(self, state: V8State) -> V8State:
        """
        执行完整的三层 Agent 流程.

        Collection ↔ Analysis 循环 → Expression → 最终输出
        """
        plan = state.execution_plan
        if not plan:
            state.final_response = "❌ 无法生成执行计划"
            state.final_status = "ERROR"
            return state

        trace_id = state.trace_id
        loop_ctx = LoopContext(max_rounds=plan.max_loop_rounds)
        last_signature = ""

        # ===== Collection ↔ Analysis Loop =====
        while loop_ctx.round < loop_ctx.max_rounds:
            loop_ctx.round += 1
            logger.info(
                f"[TRACE:{trace_id}] [Orchestrator] Loop round {loop_ctx.round}/{loop_ctx.max_rounds}"
            )

            # --- Collection ---
            collection_context = {
                "trace_id": trace_id,
                "user_input": state.user_input,
                "normalized_params": state.normalized_params,
                "loop_round": loop_ctx.round,
            }
            # 如果是补充采集，传入 additional_query
            if loop_ctx.analysis_verdicts:
                last_verdict = loop_ctx.analysis_verdicts[-1]
                if last_verdict.get("additional_query"):
                    collection_context["additional_query"] = last_verdict["additional_query"]

            collection_result = await self.collection_agent.run(plan, collection_context)
            state.collection_result = collection_result
            state.total_llm_calls += collection_result.llm_calls

            if not collection_result.success:
                logger.warning(f"[TRACE:{trace_id}] [Orchestrator] Collection failed")
                loop_ctx.terminated_reason = "collection_error"
                break

            # 无进展检测
            raw_data = collection_result.data.get("raw_summary", "")
            signature = hashlib.md5(raw_data.encode()).hexdigest()
            if signature == last_signature and loop_ctx.round > 1:
                logger.info(f"[TRACE:{trace_id}] [Orchestrator] No progress, terminating")
                loop_ctx.terminated_reason = "no_progress"
                break
            last_signature = signature
            loop_ctx.collection_results.append(collection_result.data)

            # --- Analysis ---
            analysis_context = {
                "trace_id": trace_id,
                "user_input": state.user_input,
                "collection_data": collection_result.data,
            }
            analysis_result = await self.analysis_agent.run(plan, analysis_context)
            state.analysis_result = analysis_result
            state.total_llm_calls += analysis_result.llm_calls

            if not analysis_result.success:
                loop_ctx.terminated_reason = "analysis_error"
                break

            verdict = analysis_result.data.get("verdict", {})
            loop_ctx.analysis_verdicts.append(verdict)

            # 检查是否需要追加采集
            if not analysis_result.needs_more_data:
                loop_ctx.terminated_reason = "complete"
                break

        # ===== Expression =====
        analysis_data = {}
        if state.analysis_result and state.analysis_result.success:
            analysis_data = state.analysis_result.data
        elif loop_ctx.analysis_verdicts:
            analysis_data = {"verdict": loop_ctx.analysis_verdicts[-1]}

        expression_context = {
            "trace_id": trace_id,
            "analysis_data": analysis_data,
        }
        expression_result = await self.expression_agent.run(plan, expression_context)
        state.expression_result = expression_result

        # ===== 最终输出 =====
        if expression_result.success:
            state.final_response = expression_result.data.get("response", "")
            verdict = analysis_data.get("verdict", {})
            state.final_status = verdict.get("status", "UNKNOWN")
        else:
            state.final_response = f"❌ 输出格式化失败: {expression_result.error}"
            state.final_status = "ERROR"

        # 审计
        state.loop_context = loop_ctx
        state.audit_trail.append({
            "node": "orchestrator",
            "loop_rounds": loop_ctx.round,
            "terminated_reason": loop_ctx.terminated_reason,
            "total_llm_calls": state.total_llm_calls,
        })

        logger.info(
            f"[TRACE:{trace_id}] [Orchestrator] DONE "
            f"rounds={loop_ctx.round} reason={loop_ctx.terminated_reason} "
            f"status={state.final_status}"
        )
        return state
```

- [ ] **Step 2: 编写测试**

```python
# tests/unit/test_v8_orchestrator.py
"""Orchestrator 单元测试."""
import pytest
from unittest.mock import patch, AsyncMock
from src.v8.orchestrator import Orchestrator
from src.v8.models import (
    AgentLayer, AgentResult, ExecutionPlan, V8State,
)


def _mock_collection_result(raw="跨段损耗 3.0 dB"):
    return AgentResult(
        layer=AgentLayer.COLLECTION,
        success=True,
        data={"raw_summary": raw, "tools_used": ["fiber_spanloss_query"]},
        llm_calls=1,
    )


def _mock_analysis_result(status="NORMAL", needs_more=False):
    return AgentResult(
        layer=AgentLayer.ANALYSIS,
        success=True,
        data={
            "verdict": {"status": status, "findings": [f"spanloss → {status}"]},
            "analysis_mode": "rule",
        },
        needs_more_data=needs_more,
        llm_calls=0,
    )


def _mock_expression_result(response="✅ 光纤状态：NORMAL"):
    return AgentResult(
        layer=AgentLayer.EXPRESSION,
        success=True,
        data={"response": response, "format": "narrative"},
    )


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_single_round_complete(self):
        """单轮完成：Collection → Analysis → Expression."""
        orch = Orchestrator()

        with patch.object(orch.collection_agent, "run", new_callable=AsyncMock) as mc, \
             patch.object(orch.analysis_agent, "run", new_callable=AsyncMock) as ma, \
             patch.object(orch.expression_agent, "run", new_callable=AsyncMock) as me:
            mc.return_value = _mock_collection_result()
            ma.return_value = _mock_analysis_result()
            me.return_value = _mock_expression_result()

            state = V8State(
                user_input="查看光纤1",
                trace_id="t1",
                execution_plan=ExecutionPlan(scenario_id="test", max_loop_rounds=3),
            )
            result = await orch.execute(state)

            assert result.final_status == "NORMAL"
            assert "✅" in result.final_response
            assert result.loop_context.round == 1
            assert result.loop_context.terminated_reason == "complete"

    @pytest.mark.asyncio
    async def test_multi_round_loop(self):
        """多轮循环：Analysis 要求追加数据."""
        orch = Orchestrator()

        call_count = {"n": 0}

        async def mock_analysis(plan, ctx):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _mock_analysis_result(status="UNKNOWN", needs_more=True)
            return _mock_analysis_result(status="WARNING")

        with patch.object(orch.collection_agent, "run", new_callable=AsyncMock) as mc, \
             patch.object(orch.analysis_agent, "run", side_effect=mock_analysis), \
             patch.object(orch.expression_agent, "run", new_callable=AsyncMock) as me:
            mc.return_value = _mock_collection_result("round data " + str(call_count["n"]))
            me.return_value = _mock_expression_result("⚠️ WARNING")

            state = V8State(
                user_input="全面检查光纤1",
                trace_id="t2",
                execution_plan=ExecutionPlan(max_loop_rounds=3),
            )
            result = await orch.execute(state)

            assert result.loop_context.round == 2
            assert result.final_status == "WARNING"

    @pytest.mark.asyncio
    async def test_no_plan_error(self):
        """无执行计划 → 错误."""
        orch = Orchestrator()
        state = V8State(user_input="test", trace_id="t3")
        result = await orch.execute(state)
        assert result.final_status == "ERROR"

    @pytest.mark.asyncio
    async def test_collection_failure(self):
        """Collection 失败 → 终止."""
        orch = Orchestrator()

        with patch.object(orch.collection_agent, "run", new_callable=AsyncMock) as mc, \
             patch.object(orch.expression_agent, "run", new_callable=AsyncMock) as me:
            mc.return_value = AgentResult(
                layer=AgentLayer.COLLECTION, success=False, error="timeout"
            )
            me.return_value = _mock_expression_result("❌ 数据采集失败")

            state = V8State(
                user_input="test",
                trace_id="t4",
                execution_plan=ExecutionPlan(),
            )
            result = await orch.execute(state)
            assert result.loop_context.terminated_reason == "collection_error"
```

- [ ] **Step 3: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/v8/orchestrator.py tests/unit/test_v8_orchestrator.py
git commit -m "feat(v8): implement Orchestrator with Collection↔Analysis loop"
```

---

### Task 8: v8 LangGraph 图定义（双模式入口）

**Files:**
- Create: `src/v8/graph.py`
- Modify: `src/graph/main_graph.py` (添加 v8 模式切换)
- Test: `tests/unit/test_v8_graph.py`

- [ ] **Step 1: 创建 v8 图**

```python
# src/v8/graph.py
"""
v8 LangGraph 图定义 — 双模式入口.

通过环境变量 AGENT_MODE=v8 启用新架构。
默认仍使用 v7.1 的 18 节点图。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.graph import END, START, StateGraph

from .lead_router import LeadRouter
from .models import V8State
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_router = LeadRouter()
_orchestrator = Orchestrator()


async def lead_router_node(state: dict) -> dict:
    """Lead Router 节点：解析意图 → ExecutionPlan."""
    user_input = state.get("user_input", "")
    params = state.get("normalized_params", {})
    trace_id = state.get("trace_id", "")

    plan = await _router.resolve(user_input, params, trace_id)

    return {
        "execution_plan": plan.model_dump(),
        "audit_trail": [{
            "node": "lead_router",
            "action": "resolve",
            "scenario": plan.scenario_id,
            "match_type": plan.match_type,
            "confidence": plan.confidence,
        }],
    }


async def orchestrator_node(state: dict) -> dict:
    """Orchestrator 节点：执行三层 Agent 循环."""
    from .models import ExecutionPlan

    plan_data = state.get("execution_plan", {})
    plan = ExecutionPlan.model_validate(plan_data)

    v8_state = V8State(
        user_input=state.get("user_input", ""),
        trace_id=state.get("trace_id", ""),
        session_id=state.get("session_id", ""),
        execution_plan=plan,
        normalized_params=state.get("normalized_params", {}),
    )

    result = await _orchestrator.execute(v8_state)

    return {
        "final_response": result.final_response,
        "final_status": result.final_status,
        "total_llm_calls": result.total_llm_calls,
        "audit_trail": result.audit_trail,
    }


def build_v8_graph():
    """构建 v8 精简图（3 节点）."""
    from ..graph.state import MainGraphState

    graph = StateGraph(MainGraphState)

    graph.add_node("lead_router", lead_router_node)
    graph.add_node("orchestrator", orchestrator_node)

    graph.add_edge(START, "lead_router")
    graph.add_edge("lead_router", "orchestrator")
    graph.add_edge("orchestrator", END)

    return graph.compile()


def is_v8_mode() -> bool:
    """检查是否启用 v8 模式."""
    return os.environ.get("AGENT_MODE", "").lower() == "v8"
```

- [ ] **Step 2: 修改 main_graph.py 添加模式切换**

在 `src/graph/main_graph.py` 的 `build_main_graph()` 函数开头添加：

```python
def build_main_graph():
    """Build and compile the main graph."""
    # v8 模式切换
    from ..v8.graph import is_v8_mode, build_v8_graph
    if is_v8_mode():
        logger.info("[MainGraph] AGENT_MODE=v8, using v8 three-layer architecture")
        return build_v8_graph()

    # ... 原有 v7.1 代码不变 ...
```

- [ ] **Step 3: 编写测试**

```python
# tests/unit/test_v8_graph.py
"""v8 图定义测试."""
import pytest
from unittest.mock import patch
from src.v8.graph import is_v8_mode, build_v8_graph


class TestV8Mode:
    def test_default_mode_is_not_v8(self):
        with patch.dict("os.environ", {}, clear=True):
            assert not is_v8_mode()

    def test_v8_mode_enabled(self):
        with patch.dict("os.environ", {"AGENT_MODE": "v8"}):
            assert is_v8_mode()

    def test_v8_mode_case_insensitive(self):
        with patch.dict("os.environ", {"AGENT_MODE": "V8"}):
            assert is_v8_mode()

    def test_build_v8_graph_compiles(self):
        """v8 图可以成功编译."""
        graph = build_v8_graph()
        assert graph is not None
```

- [ ] **Step 4: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/v8/graph.py src/graph/main_graph.py tests/unit/test_v8_graph.py
git commit -m "feat(v8): add v8 graph with dual-mode entry (AGENT_MODE=v8)"
```

---

### Task 9: Skill YAML 适配 — 添加 v8 扩展字段

**Files:**
- Modify: `src/skills/schema.py` (添加 V8Config 模型)
- Modify: `skills/spanloss_check.yaml` (添加 v8 字段示例)
- Modify: `src/v8/lead_router.py` (使用 v8 字段)
- Test: `tests/unit/test_v8_skill_compat.py`

- [ ] **Step 1: 扩展 SkillDefinition schema**

在 `src/skills/schema.py` 中添加：

```python
class V8Config(BaseModel):
    """v8 三层架构扩展配置（可选，向后兼容）."""
    analysis_mode: Literal["rule_first", "llm_only", "rule_only"] = "rule_first"
    output_format: Literal["narrative", "table", "report", "raw"] = "narrative"
    max_loop_rounds: int = Field(default=3, ge=1, le=10)
    threshold_refs: list[str] = Field(default_factory=list)
```

在 `SkillDefinition` 中添加字段：

```python
class SkillDefinition(BaseModel):
    # ... 现有字段 ...
    v8: Optional[V8Config] = Field(default=None, description="v8 三层架构扩展配置")
```

- [ ] **Step 2: 在 spanloss_check.yaml 中添加 v8 字段**

```yaml
# 在文件顶层添加（与 routing 同级）
v8:
  analysis_mode: "rule_first"
  output_format: "narrative"
  max_loop_rounds: 3
  threshold_refs:
    - "default_spanloss"
    - "optical_power"
```

- [ ] **Step 3: 修改 LeadRouter 使用 v8 字段**

在 `src/v8/lead_router.py` 的 `_rule_match` 方法中：

```python
# 如果 skill 有 v8 配置，使用它
v8_cfg = skill.v8
return ExecutionPlan(
    ...
    analysis_mode=v8_cfg.analysis_mode if v8_cfg else "rule_first",
    output_format=v8_cfg.output_format if v8_cfg else "narrative",
    max_loop_rounds=v8_cfg.max_loop_rounds if v8_cfg else 3,
    threshold_refs=v8_cfg.threshold_refs if v8_cfg else [],
)
```

- [ ] **Step 4: 编写兼容性测试**

```python
# tests/unit/test_v8_skill_compat.py
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
```

- [ ] **Step 5: 运行测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_skill_compat.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/skills/schema.py skills/ src/v8/lead_router.py tests/unit/test_v8_skill_compat.py
git commit -m "feat(v8): extend SkillDefinition with optional v8 config (backward compatible)"
```

---

### Task 10: 端到端集成测试 + 全量回归

**Files:**
- Create: `tests/integration/test_v8_e2e.py`
- Run: 全量测试

- [ ] **Step 1: 编写 v8 端到端测试**

```python
# tests/integration/test_v8_e2e.py
"""
v8 三层架构端到端集成测试.

使用 mock 后端（不需要真实 C++ 服务），验证完整流程：
User Input → Lead Router → Orchestrator → Collection → Analysis → Expression → Response
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.v8.models import V8State, ExecutionPlan
from src.v8.orchestrator import Orchestrator
from src.v8.lead_router import LeadRouter


class TestV8EndToEnd:
    """完整流程测试."""

    @pytest.mark.asyncio
    async def test_spanloss_normal_flow(self):
        """正常跨段损耗查询 → 完整三层流程."""
        router = LeadRouter()
        orch = Orchestrator()

        # Lead Router 解析
        plan = await router.resolve(
            "查看光纤1的跨段损耗",
            {"fiber_ids": [1]},
            trace_id="e2e-001",
        )
        assert plan.scenario_id != ""

        # Mock Collection 返回正常数据
        with patch.object(
            orch.collection_agent, "run", new_callable=AsyncMock
        ) as mock_collect:
            from src.v8.models import AgentResult, AgentLayer
            mock_collect.return_value = AgentResult(
                layer=AgentLayer.COLLECTION,
                success=True,
                data={"raw_summary": "光纤1 跨段损耗 2.8 dB，OOP -5.2 dBm"},
                llm_calls=1,
            )

            state = V8State(
                user_input="查看光纤1的跨段损耗",
                trace_id="e2e-001",
                execution_plan=plan,
                normalized_params={"fiber_ids": [1]},
            )
            result = await orch.execute(state)

            assert result.final_status in ("NORMAL", "WARNING", "CRITICAL")
            assert result.final_response != ""
            assert result.loop_context.terminated_reason == "complete"
            assert result.total_llm_calls >= 1

    @pytest.mark.asyncio
    async def test_critical_alarm_flow(self):
        """严重告警 → CRITICAL 输出."""
        orch = Orchestrator()

        with patch.object(
            orch.collection_agent, "run", new_callable=AsyncMock
        ) as mock_collect:
            from src.v8.models import AgentResult, AgentLayer
            mock_collect.return_value = AgentResult(
                layer=AgentLayer.COLLECTION,
                success=True,
                data={"raw_summary": "光纤3 跨段损耗 9.5 dB，OOP -15.0 dBm"},
                llm_calls=1,
            )

            plan = ExecutionPlan(
                scenario_id="spanloss_check",
                tools=["fiber_spanloss_query"],
                output_format="narrative",
            )
            state = V8State(
                user_input="光纤3怎么了",
                trace_id="e2e-002",
                execution_plan=plan,
            )
            result = await orch.execute(state)

            assert result.final_status == "CRITICAL"
            assert "🚨" in result.final_response

    @pytest.mark.asyncio
    async def test_loop_terminates_at_max_rounds(self):
        """循环在 max_rounds 时终止."""
        orch = Orchestrator()

        from src.v8.models import AgentResult, AgentLayer

        round_counter = {"n": 0}

        async def always_need_more(plan, ctx):
            round_counter["n"] += 1
            return AgentResult(
                layer=AgentLayer.ANALYSIS,
                success=True,
                data={"verdict": {"status": "UNKNOWN", "findings": []}},
                needs_more_data=True,
                additional_query={"reason": "需要更多数据", "tool": "alarm_query"},
            )

        async def collection_with_varying_data(plan, ctx):
            return AgentResult(
                layer=AgentLayer.COLLECTION,
                success=True,
                data={"raw_summary": f"data round {round_counter['n']} unique"},
                llm_calls=1,
            )

        with patch.object(orch.collection_agent, "run", side_effect=collection_with_varying_data), \
             patch.object(orch.analysis_agent, "run", side_effect=always_need_more), \
             patch.object(orch.expression_agent, "run", new_callable=AsyncMock) as me:
            me.return_value = AgentResult(
                layer=AgentLayer.EXPRESSION,
                success=True,
                data={"response": "❓ 数据不足", "format": "narrative"},
            )

            plan = ExecutionPlan(max_loop_rounds=3)
            state = V8State(user_input="test", trace_id="e2e-003", execution_plan=plan)
            result = await orch.execute(state)

            assert result.loop_context.round == 3
            assert result.loop_context.terminated_reason == "max_rounds"
```

- [ ] **Step 2: 运行 v8 全部测试**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/test_v8_*.py tests/integration/test_v8_e2e.py -v`
Expected: ALL PASS

- [ ] **Step 3: 全量回归（确保 v7.1 不受影响）**

Run: `cd e:\Work\FiberMaintain\Agent\LangGraph-agent && .venv\Scripts\python.exe -m pytest tests/unit/ -v --tb=short`
Expected: ALL PASS（包括原有 164 个测试 + 新增 v8 测试）

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_v8_e2e.py
git commit -m "test(v8): add end-to-end integration tests for three-layer architecture"
```

---

## 迁移检查清单

| 检查项 | 验证方式 |
|--------|----------|
| v7.1 默认模式不受影响 | `AGENT_MODE` 未设置时走旧图 |
| v8 模式可切换 | `AGENT_MODE=v8` 走新图 |
| Skill YAML 向后兼容 | 无 v8 字段的 YAML 正常加载 |
| 阈值仍从 thresholds.yaml 获取 | AnalysisAgent 使用 ThresholdEngine |
| 反幻觉仍生效 | ExpressionAgent 调用 validate_narration_numbers |
| 循环终止保障 | max_rounds + no_progress + error 三重终止 |
| 审计链完整 | audit_trail 记录每层 Agent 执行 |

## 后续演进（不在本次范围）

- [ ] 将 16 个 Skill YAML 全部添加 v8 routing 字段
- [ ] 前端添加 v8 模式切换开关
- [ ] 灰度发布：10% 流量走 v8，对比质量指标
- [ ] 移除 v7.1 旧图（确认 v8 稳定后）
- [ ] Collection Agent 支持并行工具调用
- [ ] Expression Agent 支持多语言输出
