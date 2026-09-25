# 配置化 Skill + 声明式规则引擎 — 设计文档

> **日期**: 2026-08-02
> **状态**: 已批准
> **范围**: LangGraph-agent 扩展性改造

## 1. 背景与问题

当前系统新增一个判断场景（如"光纤色散分析"）需要修改 **9 个 Python 文件**：

| # | 文件 | 修改内容 |
|---|------|---------|
| 1 | `src/tools/dispersion_tools.py` | 新建 Tool（调后端 API） |
| 2 | `src/tools/__init__.py` | 注册 Tool + 加入 DATA_COLLECTOR_TOOLS |
| 3 | `src/nodes/rule_engine.py` | 新增正则规则 |
| 4 | `src/nodes/fast_path_executor.py` | 新增 `_query_*()` + 模板 |
| 5 | `src/graph/state.py` | IntentResult.intent Literal 新增 |
| 6 | `src/graph/routing.py` | data_intents 元组新增 |
| 7 | `src/nodes/rule_judgment.py` | 新增阈值判断逻辑 |
| 8 | `src/nodes/intent_classifier.py` | INTENT_PROMPT 新增意图描述 |
| 9 | `src/config.py` | 新增阈值常量 |

这是典型的 **Shotgun Surgery** 反模式。

### 设计目标

- 新增场景：从改 9 个文件 → 写 1 个 YAML 文件
- 全量迁移现有 25+ 条硬编码规则到 YAML
- 覆盖 Fast Path + Normal Path 全路径
- 支持启动加载 + 热加载 API（无需重启）
- 运维人员可自行配置新规则（无需开发介入）

### 不做什么

- **不引入 MCP**：单 Agent、固定工具集、延迟敏感（ADR-003）
- **不引入 Plugin 系统**：领域固定，不需要运行时加载代码
- **不支持第三方 Skill 市场**：非平台化定位

## 2. 方案选择

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A: 单文件 Skill** ✅ | 一个场景 = 一个 YAML | 认知负担最低 | 复杂场景 YAML 较长 |
| B: 分层目录 | 一个场景 = 一个目录 | 关注点分离 | 散落 5 文件，改善有限 |
| C: YAML + Hook | YAML + Python 插件 | 灵活性最高 | 安全风险，两套机制 |

**选定方案 A**：光纤维护的判断逻辑都是"阈值比较 + 模式匹配"，YAML 完全能表达。

## 3. Skill YAML Schema

```yaml
# ============================================================
# Skill 定义文件 — 完整 Schema
# ============================================================

# --- 元信息 ---
id: string                  # 唯一标识（不可重复）
name: string                # 显示名称
version: string             # 版本号
description: string         # 描述
author: string              # 作者

# --- 触发规则（注册到 RuleEngine）---
triggers:
  - pattern: string         # 正则表达式
    params:                 # 参数提取
      <param_name>:
        group: int          # 正则捕获组编号
        type: int | str | float  # 类型转换
    confidence: float       # 置信度（规则命中 = 1.0）

# --- 路由配置（注册到 route_by_intent）---
routing:
  intent: string            # 意图标识
  group: data_query | batch | knowledge | report | chitchat
  fast_path_eligible: bool  # 是否可走 Fast Path
  template_id: string       # Fast Path 使用的模板 ID

# --- 工具定义（Fast Path 直接调用 / Normal Path 注入 data_collector）---
# Fast Path skill: 必填，定义直接调用的 API
# Normal Path skill: 可空（由 collector_tools 引用已有工具）
tools:
  - id: string              # 工具标识
    endpoint: string        # API 路径（支持 {param} 占位符）
    method: GET | POST
    timeout: float          # 超时秒数
    params:                 # 请求参数
      <key>: "{param}"      # 从 triggers.params 取值
    response_extract:       # 从响应中提取关键值
      <field>: "$.jsonpath" # JSONPath 表达式

# --- 判断规则（注册到 JudgmentEngine）---
judgment:
  metric: string            # 指标名称
  extract_pattern: string   # 从 data_summary 提取值的正则
  conditions:               # 按优先级从高到低
    - op: ">" | "<" | "not_in_range" | "contains" | "==" | "count_gt"
      value: string         # 阈值（支持 ${CONFIG_VAR} 引用）
      status: CRITICAL | WARNING | NORMAL
      finding: string       # 判断结论模板（支持 {value}, {percent}）
  default:
    status: NORMAL
    finding: string
  actions:                  # 按 status 给出建议
    CRITICAL: [string]
    WARNING: [string]

# --- 输出模板（注册到 FastPathExecutor）---
template:
  fast_path: string         # Fast Path 输出模板
  status_map:               # status → 状态文本
    CRITICAL: string
    WARNING: string
    NORMAL: string

# --- Normal Path 工具组（注入 data_collector 的 ReAct Agent）---
# 仅 fast_path_eligible=false 时生效
# 若为空，则使用 tools 字段动态生成的 LangChain Tool
collector_tools: [string]   # 已有工具函数名列表（引用 src/tools/ 中的 @tool）

# --- 测试用例（自动回归验证）---
test_cases:
  - input: string           # 用户输入
    expected_intent: string
    expected_params: dict
    expected_fast_path: bool
```

### 变量替换规则

| 语法 | 含义 | 示例 |
|------|------|------|
| `${VAR}` | 引用 config.py 环境变量 | `${SPANLOSS_THRESHOLD}` → 5.0 |
| `{field}` | 引用运行时数据 | `{fiber_id}` → 3 |
| `$.path` | JSONPath（API 响应提取） | `$.spanloss` → 4.2 |

## 4. SkillLoader 架构

### 组件交互

```
启动 / POST /api/v1/skills/reload
            │
            ▼
┌─────── SkillLoader ──────────────────────────────┐
│  scan(skills/*.yaml)                             │
│  → parse → validate (Pydantic)                   │
│  → register to 6 Registries                      │
└──────────────────────────────────────────────────┘
            │
    ┌───────┼───────┬───────────┬──────────┐
    ▼       ▼       ▼           ▼          ▼
Trigger  Tool    Judgment   Template  Routing
Registry Registry Registry  Registry  Registry
    │       │       │           │          │
    ▼       ▼       ▼           ▼          ▼
Rule    FastPath  Rule       FastPath   routing.py
Engine  Executor  Judgment   Executor
```

### 核心接口

```python
class SkillLoader:
    def __init__(self, skills_dir: Path): ...
    def load_all(self) -> int: ...
    def reload(self) -> int: ...
    def get_skill(self, skill_id: str) -> SkillDefinition | None: ...
    def get_tools_for_intent(self, intent: str) -> list[BaseTool]: ...
    def all_skills(self) -> list[SkillDefinition]: ...
```

### 注册机制

| 组件 | 当前 | 改造后 |
|------|------|--------|
| `RuleEngine.match()` | 遍历 `_COMPILED_RULES` | 遍历 `TriggerRegistry.get_compiled()` |
| `fast_path_executor_node()` | if-elif 调用 `_query_*` | `ToolRegistry.execute(intent, params)` |
| `rule_judgment_node()` | if-else 链 | `JudgmentEngine.evaluate(data_summary)` |
| `_render_template()` | `TEMPLATES[id]` | `TemplateRegistry.render(id, data)` |
| `route_by_intent()` | 硬编码元组 | `RoutingRegistry.resolve(intent)` |
| `data_collector` | 固定 `DATA_COLLECTOR_TOOLS` | `SkillLoader.get_tools_for_intent(intent)` |

### 热加载语义

- **原子性**：新规则全部解析成功后一次性切换，旧规则继续服务
- **失败回滚**：任何 YAML 解析失败 → 整批拒绝，保持旧注册表
- **无中断**：不需要重启服务

## 5. 声明式判断引擎

### 设计

```python
class JudgmentEngine:
    """通用声明式判断引擎。"""

    def register(self, skill: SkillDefinition) -> None:
        """从 Skill 的 judgment 字段注册判断规则。"""

    def evaluate(self, data_summary: str) -> RuleJudgment:
        """对 data_summary 逐条规则匹配，返回结构化判断。"""

    def clear(self) -> None:
        """清空所有规则（热加载前调用）。"""
```

### 条件操作符

| 操作符 | 含义 | 示例 |
|--------|------|------|
| `>` | 大于 | spanloss > 5.0 |
| `<` | 小于 | oop < -8.0 |
| `not_in_range` | 不在范围内 | oop not_in (-8, -2) |
| `contains` | 包含子串 | data contains "CRITICAL" |
| `==` | 等于 | color == "RED" |
| `count_gt` | 计数大于 | alarm_count count_gt 0 |

### 统一判断

Fast Path 和 Normal Path **共用同一个 JudgmentEngine**：
- Fast Path: API 响应 → JudgmentEngine.evaluate() → TemplateRegistry.render()
- Normal Path: data_collector 输出 → JudgmentEngine.evaluate() → narrator 表述

## 6. 迁移计划

### 规则映射

| 现有规则 | 目标 YAML | 类型 |
|---------|-----------|------|
| R001, R105 | `spanloss_query.yaml` | Fast Path |
| R002, R101 | `connection_query.yaml` | Fast Path |
| R003, R090 | `performance_query.yaml` | Fast Path |
| R004 | `fiber_alarm_query.yaml` | Fast Path |
| R010 | `port_alarm_query.yaml` | Fast Path |
| R005, R100, R102 | `fiber_status_query.yaml` | Fast Path |
| R011 | `board_query.yaml` | Fast Path |
| R020-R022, R103 | `colored_query.yaml` | Fast Path |
| R030, R031 | `stats_query.yaml` | Fast Path |
| R032 | `trend_query.yaml` | Fast Path |
| R050, R051 | `color_diagnosis.yaml` | Normal Path |
| R052, R104 | `spanloss_analysis.yaml` | Normal Path |
| R080 | `health_check.yaml` | Normal Path |
| R070, R071 | `batch_query.yaml` | Normal Path |
| R040 | `knowledge_qa.yaml` | Normal Path |
| R060 | `report_generation.yaml` | Normal Path |

**25 条规则 → 16 个 YAML 文件**

### 分阶段实施

| Phase | 内容 | 产出 |
|-------|------|------|
| 1 | 搭建骨架 | `src/skills/` 模块 + 2-3 个示例 YAML |
| 2 | 改造消费端 | 各节点从 Registry 读取（保留 fallback） |
| 3 | 全量迁移 | 16 个 YAML + 删除硬编码 |
| 4 | 热加载 + 测试 | reload API + 自动回归测试 |

### Fallback 机制

迁移期间，如果 `skills/` 目录为空或加载失败，系统 fallback 到原有硬编码逻辑。
全量迁移完成并验证后，删除 fallback 代码。

## 7. 测试策略

| 层级 | 测试内容 | 实现方式 |
|------|---------|---------|
| L1 | YAML Schema 验证 | Pydantic ValidationError |
| L2 | 触发匹配 | 从 `test_cases` 字段自动生成参数化测试 |
| L3 | 端到端 Fast Path | mock HTTP → 判断 → 模板渲染 |

新增 Skill 时，只要在 YAML 中写了 `test_cases`，测试自动覆盖。

## 8. 文件结构

```
Agent/LangGraph-agent/
├── skills/                          # Skill 定义目录
│   ├── spanloss_query.yaml
│   ├── connection_query.yaml
│   ├── ...（共 16 个）
│   └── _schema.json                # JSON Schema（IDE 提示）
├── src/skills/                      # Skill 引擎模块
│   ├── __init__.py
│   ├── schema.py                   # Pydantic 模型
│   ├── loader.py                   # SkillLoader
│   ├── registries.py              # 6 个 Registry
│   └── judgment_engine.py          # 声明式判断引擎
└── tests/
    └── test_skills_auto.py         # 自动回归测试
```

## 9. 关联 ADR

- **ADR-003**: 不将后端接口改造为 MCP（单 Agent、固定工具、延迟敏感）
- **ADR-004**: 采用配置化 Skill 机制替代硬编码扩展（本文档）
- **ADR-005**: 将 rule_judgment 从 if-else 重构为声明式规则引擎
