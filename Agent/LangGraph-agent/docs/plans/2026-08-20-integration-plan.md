# 未接线功能集成方案与可删除文件分析

> 依据 `docs/plans/2026-08-20-ch2to6-landing-plan.md` 与《AI Agent 设计原理与工程实践》第2-6章建议，
> 对已实现但未接入运行时的 6 项功能进行集成方案设计，同时分析可删除/被替代的文件。
> 创建日期：2026-08-20 | 本文为方案文档，不包含代码改动。

---

## 结论先行

**6 项已实现未接线功能**分布在 4 个章节，按接入优先级排序：

| 优先级 | 功能 | 章节 | 接入成本 | 核心理由 |
|---|---|---|---|---|
| **P0** | user_memory → v7.1 result_aggregator / v8 ExpressionAgent | 3 | 低 | 书中明确"个性偏好决定输出表达"，代码已就绪，仅缺一行调用 |
| **P0** | output_filter → v7.1 result_aggregator 输出前 | 2 | 低 | v7.1 输出侧无脱敏，v8 已有 output_guard，形成不对称 |
| **P1** | consolidator → 支持维护脚本/健康端点 | 3 | 低 | 经验积累到一定量后需落地，否则经验表只增不整理 |
| **P1** | tool_reviewer → 插入 ToolExecutor 或 confirmation_gate 后 | 4 | 中 | 书第4章"提案者-审核者"分离，但当前业务确实无写工具安全事件 |
| **P2** | code_orchestrator → 注册为 Tool | 5 | 中 | 第5章"错误恢复+保留集"是 Coding Agent 核心，但当前业务无代码生成需求 |
| **P3** | aci_spec / dynamic_discovery → 删除 | 4 | 0 | 无运行时引用，工具契约已通过 ToolResult 实现 |

**可删除/被替代文件 2 个**（书中建议不冲突，纯冗余）：

| 文件 | 现状 | 被替代者 | 建议 |
|---|---|---|---|
| `src/tools/dynamic_discovery.py` | 无运行时调用，仅 test_p2_features 测试 | 静态 `tools/__init__.py` 工具分组 | 删除 |
| `src/tools/aci_spec.py` | 仅被 dynamic_discovery 引用，均无运行时调用 | 工具的 `description` / `ToolResult` 契约 | 若 dynamic_discovery 删除，可一并删除；或保留以备后续工具注册表 |

---

## 一、各功能集成方案

### 1.1 user_memory 注入输出侧（P0，书中第3章）

**现状**：`src/memory/user_memory.py` 定义了 `UserMemoryManager.inject_preferences`，但 **无任何运行时调用者**。plan 文档声称"注入 ExpressionAgent 输出格式选择"，实际没有。

**接线点**（两处，都是注入"输出格式偏好"到上下文）：

| 架构 | 接线位置 | 改动（一行代码） |
|---|---|---|
| v7.1 | `src/nodes/result_aggregator.py:51` 在组装 final output 前 | `state["output_format"] = get_user_memory_manager().inject_preferences(user_id, state).get("output_format", "narrative")` |
| v8 | `src/v8/agents/expression_agent.py:54` 在 `execute()` 入口 | `plan.output_format = get_user_memory_manager().inject_preferences(user_id, {"output_format": plan.output_format}).get("output_format", plan.output_format)` |

**前提条件**：
- `state` 中需有 `user_id` 字段（当前 `MainGraphState` 无此字段，需从 `config` 或 `thread_id` 派生）
- 若 `user_id` 不可得，跳过注入（不报错）

**验证**：`inject_preferences` 无 LLM 调用，纯 dict 操作，测试已在 `test_user_memory.py`。

---

### 1.2 output_filter 接入 v7.1 输出侧（P0，书中第2/4章"输出护栏"）

**现状**：`src/security/output_filter.py` 定义了 `OutputFilter.filter()` 做 IP/端口掩码 + 错误脱敏，按角色区分。但 **无节点调用**。v8 输出侧已有 `src/v8/output_guard.py`（PII 检测+结构化验证+脱敏），v7.1 输出侧无任何脱敏。

**接线点**：

| 架构 | 接线位置 | 改动 |
|---|---|---|
| v7.1 | `src/nodes/result_aggregator.py:52` 在 `final_output` 返回前 | `output = output_filter.filter(output)` 对 `final_output` 做脱敏 |
| v8 | 已有 `output_guard.py`，无需再接 | 无需改动 |

**前提条件**：角色 `role` 从 `config.py` 或 `state` 中读取（默认 `operator`）。

**与 output_guard 的关系**：
- `output_filter`（v7.1）：IP/端口掩码 + 错误脱敏（按角色管理端/运营端区分）
- `output_guard`（v8）：PII 检测 + 结构化验证 + 品牌一致（更全面的输出护栏）
- 两者功能互补但不重复。若将来 v7.1 迁移到 v8，可统一归到 `output_guard`。

---

### 1.3 consolidator 接入维护接口（P1，书中第3章"保存≠学习"）

**现状**：`src/memory/consolidator.py` 定义了 `ExperienceConsolidator.consolidate()`，支持去重合并/过期标记/超量淘汰/dry_run。但 `get_consolidator` **无任何调用者**。

**接线点**（两处，均不插入在线推理路径）：

| 位置 | 改动方式 | 说明 |
|---|---|---|
| `src/frontend_api.py` 新增 POST `/api/v1/memory/consolidate` | 路由处理函数调用 `get_consolidator().consolidate(dry_run=...)` | 供运维手动触发，支持 `dry_run=true` 预览 |
| `src/server.py` 启动时注册定时任务 | `asyncio.create_task(_consolidate_loop())` 每小时执行一次 | 可选，不强制；大型经验库场景才需要 |

**验证**：`test_consolidator.py` 已覆盖 6 例（合并/不合并/过期/超量/dry_run/旧表兼容）。

---

### 1.4 tool_reviewer 插入写工具执行链（P1，书中第4章"提案者-审核者分离"）

**现状**：`src/security/tool_reviewer.py` 定义了 `ToolReviewer.review()`（纯代码复核，参数类型白名单+高风险约束正则+空参数检查），`get_tool_reviewer` **无任何调用者**。当前写工具门禁：
```
前端 → POST /api/v1/tools/confirm (confirmation_gate) → 工具执行
```
无服务端复核环节。

**接线点**（两选一，推荐方案 B）：

| 方案 | 位置 | 改动 | 优缺点 |
|---|---|---|---|
| A：在 `ToolExecutor.run` 末尾 | `src/tools/tool_result.py:ToolExecutor.run` | 对 HIGH 风险工具返回结果前调用 `reviewer.review()` | 一次改到处生效，但 `review` 在工具执行后，不能阻止执行 |
| B：在 `pullcall_tools.py` 确认后执行前 | `src/tools/pullcall_tools.py:56` 在 `get_confirmation_gate().request()` 之前 | 插入 `reviewer.review(tool_name, params)`，若返回 `block` 则拒绝请求 | 提案者-审核者分离，推荐 |

**建议方案 B**，因为：
- `confirmation_gate` 是前端 HITL（用户确认），`tool_reviewer` 是服务端机制（参数校验），分离在代码中清晰对应"两阶段审核"。
- 方案 B 在 `request()` 之前，能在源头阻止无效参数写意图进入前端确认面板。

---

### 1.5 code_orchestrator 注册为 Tool（P2，书中第5章"代码作为元能力"）

**现状**：`src/tools/code_orchestrator.py` 定义了 `CodeOrchestrator`，支持 `execute_plan_with_recovery`（失败重建+保留集校验）。但 **未注册为任何 Tool**（`src/tools/__init__.py` 无引用），无图节点调用，仅单测覆盖。

**接线点**（三步）：

1. **注册为 Tool**：在 `src/tools/__init__.py` 增加 `from .code_orchestrator import execute_code_plan` 并加入 `DATA_COLLECTOR_TOOLS` 或新增 `CODING_TOOLS` 分组
2. **包装为工具函数**：在 `code_orchestrator.py` 新增顶层函数，接收 `code_plan_json` 参数，返回 `ToolResult` 类型
3. **绑定到图**：目前 v7.1/v8 均无代码执行场景，所以步骤 2 注册后即足够，不绑定到现有节点。等需要代码生成与分析的业务场景出现时，再在 `intent_router` 添加 `code_execution` 路由

**前提条件**：当前业务"光纤维护"无代码生成需求。此功能仅当系统扩展为"运维 Agent 能自动编写分析脚本"时启用。

---

## 二、可删除/被替代文件分析

### 2.1 `src/tools/dynamic_discovery.py`（建议删除）

**当前状态**：定义 `DynamicToolDiscovery` 类，支持 `scan_module`（扫描模块自动发现工具函数）、`register_discovered`（注册到 ACI Registry）、`find_tools_for_intent`（按意图关键词搜索工具）。

**为什么建议删除**：
- 全书第4章"工具动态发现"场景是"Agent 运行时动态发现并注册新工具"，当前系统全部 23+ 工具在 `tools/__init__.py` 静态注册，无动态发现需求。
- `find_tools_for_intent` 功能被 `Skill 系统`的 `trigger` 正则和 `LeadRouter` 的路由逻辑替代——Skill 按意图精准匹配，无需 keyword 模糊搜索。
- 无任何运行时调用者，仅 `test_p2_features.py` 测试。
- 删除后不影响任何在线或评估链路。

**删除需要同步**：
- `src/tools/__init__.py` 移除 `from .dynamic_discovery import ...`（如有）
- `tests/unit/test_p2_features.py` 中 `TestToolDiscovery` 相关测试 → 删除或移到归档
- `src/tools/dynamic_discovery.py` 文件本身 → 删除

### 2.2 `src/tools/aci_spec.py`（建议保留或删除权衡）

**当前状态**：定义 `ACIRegistry`、`ToolSpec`、`ToolParameter` 等 ACI 契约模型，提供 `get_aci_registry()` 注册表。**仅被 `dynamic_discovery.py` 引用**，无其他运行时调用者。

**保留理由**：
- ACI（Agent-Computer Interface）契约是书第4章明确提出的工具描述标准，虽然当前系统通过 Tool 的 `description` 和 `ToolResult` 实现了契约，但 `aci_spec.py` 提供了一个更结构化的注册表视图。
- 若未来扩展工具自动发现/注册，`aci_spec.py` 是基础的。

**删除理由**：
- 当前无运行时引用，且功能被 `tools/__init__.py` 的静态分组 + Tool 的 `description` 字段替代。
- 保持 `aci_spec.py` 意味着维护两个工具描述系统（代码中的 `description` + ACI Registry），增加认知负担。

**建议**：若删除 `dynamic_discovery.py`，同步删除 `aci_spec.py`。若不删除 `aci_spec.py`，应将其"工具描述"与现有工具的 `description` 字段对齐，并接入 `server.py` 的 `/health` 端点作为工具注册表白名单验证。

---

## 三、删除 vs 集成决策树

```
各未接线功能，是否集成？

是否触及安全/信任边界？
  ├─ 是 → tool_reviewer（P1，安全边界，宁紧勿松）
  └─ 否 → 继续

是否有明确的当前业务痛点？
  ├─ 是 → user_memory（P0）、output_filter（P0）、consolidator（P1）
  └─ 否 → 继续

是否有书明确要求但当前不痛？
  ├─ 是 → code_orchestrator（P2，书第5章核心，但光纤维护无代码场景）
  └─ 否 → 延迟

各文件是否删除？

是否有运行时调用者？
  ├─ 有 → 不可删除，应集成
  └─ 无 → 继续

是否有替代者？
  ├─ 是 → 可删除：dynamic_discovery（被 Skill 系统替代）
  └─ 否 → 保留或集成：user_memory（无替代，需集成）
```

---

## 四、验收标准

每个集成项完成后的验收标准：

1. **已有单测不退化**：`pytest tests/unit/ -q` 通过率不下降。
2. **回归测试通过**：`pytest tests/test_regression.py tests/test_rule_engine_v72.py tests/eval/ -q` 通过。
3. **新接线点有单测覆盖**：新增/修改的接线逻辑至少 1 个正向测试 + 1 个降级测试（跳过）。
4. **不影响在线路径**：接线点前的代码若不能执行（如 `user_id` 缺失），静默跳过，不抛异常。
5. **方案文档更新**：`docs/多Agent组件全面分析.md` 第 8 章同步更新接线状态。

---

## 五、附录：完整核查对照表

### 5.1 plan 文档各章节功能使用状态

| 章节 | 功能（plan 文档声称） | 文件 | 实际接入状态 |
|---|---|---|---|
| 2 | 上下文压缩 + 摘要 | `memory/context_compressor.py` | ✅ v7.1 input_guard + v8 graph 均调用 |
| 2 | 状态栏/预算/降级统计 | `nodes/status_bar.py` | ✅ v7.1 analysis_expert 注入 |
| 2 | 注入防御（9 条正则+长度截断） | `nodes/input_guard.py` | ✅ v7.1 图首节点 |
| 2 | 注入检测分层（弱规则标记） | `nodes/input_guard.py:47-80` | ✅ v7.1 生效；v8 `security.py` 无分层 |
| 2 | TaskContext 任务内记忆 | `context/task_context.py` | ✅ v7.1 链路生效 |
| 2 | 输出过滤（按角色脱敏） | `security/output_filter.py` | ✅ [v7.4] 接入 `result_aggregator` 全部输出路径 |
| 3 | 用户记忆/个性偏好 | `memory/user_memory.py` | ✅ [v7.4] v7.1 `result_aggregator` + v8 `expression_agent` 注入 |
| 3 | 经验存储/去重 | `memory/experience_store.py` | ✅ v7.1+v8 均调用 |
| 3 | 经验写入质量 veto | `memory/experience_store.py:69-79` | ✅ 内部生效 |
| 3 | 经验复盘/整合/淘汰 | `memory/consolidator.py` | ✅ [v7.4] 接入 `frontend_api` 维护端点 |
| 3 | RAG 混合检索 | `rag/engine.py` | ✅ v8 analysis_agent + v7.1 knowledge_qa 调用 |
| 4 | ToolResult 结构化返回 | `tools/tool_result.py` | ✅ 全部工具统一经 ToolExecutor |
| 4 | 风险分级 + 动态升级 + 确认门禁 | `governance/tool_risk.py` | ✅ [v7.4] 经 `tool_reviewer` 间接引用（风险分级） |
| 4 | 确认门禁 HITL | `tools/confirmation_gate.py` | ✅ `pullcall_tools.py` + `frontend_api.py` 调用 |
| 4 | 服务端独立复核 | `security/tool_reviewer.py` | ✅ [v7.4] `pullcall_tools` 确认前调用 |
| 4 | degraded 语义完善 | `tools/tool_result.py` + `nodes/status_bar.py` | ✅ `ToolExecutor` 超时归 degraded |
| 4 | 工具契约 ACI + 动态发现 | `tools/aci_spec.py` `dynamic_discovery.py` | ⛔ 仅互引，无运行时调用（建议删除） |
| 5 | code_orchestrator 失败重建+保留集 | `tools/code_orchestrator.py` | ✅ [v7.4] 注册为 `execute_code_plan` Tool + `CODING_TOOLS` 分组 |
| 6 | 承诺-行动一致性 + 无证据陈述 | `tests/eval/checks.py` | 🔬 仅评估链路 |
| 6 | 异源裁判 | `tests/eval/rubric_judge.py` | 🔬 仅评估链路 |
| 6 | Pass@k / 错误归因聚合 | `tests/eval/failure_diagnosis.py` `e2e_runner.py` `run_eval.py` | 🔬 仅评估链路 |

### 5.2 配置/常量是否一致

| config 常量 | 用途 | 是否有运行时引用 |
|---|---|---|
| `USER_MEMORY_DB` | 用户记忆数据库路径 | ✅ [v7.4] 经 `user_memory` → `result_aggregator` / `expression_agent` 运行时引用 |
| 其余常量 | 均被运行时引用 | ✅ |

---

## 六、落地记录（2026-08-20）

> 本方案的 5 项集成已全部落地，验收通过。

| 集成项 | 状态 | 改动文件 | 单测 |
|---|---|---|---|
| P0 user_memory 注入 | ✅ | `nodes/result_aggregator.py` `v8/agents/expression_agent.py` `graph/state.py` `v8/models.py` `v8/graph.py` `v8/orchestrator.py` | `test_v8_expression_agent.py`（注入/降级/异常）`test_result_aggregator.py` |
| P0 output_filter 接入 | ✅ | `nodes/result_aggregator.py` | `test_result_aggregator.py`（IP/错误脱敏） |
| P1 consolidator 维护端点 | ✅ | `frontend_api.py`（POST `/api/v1/memory/consolidate`） | `test_server_api.py::TestConsolidateEndpoint` |
| P1 tool_reviewer 复核前置 | ✅ | `tools/pullcall_tools.py`（`_pending_confirmation_json` 内） | `test_tool_reviewer.py::TestPullCallReviewerIntegration` |
| P2 code_orchestrator 注册 Tool | ✅ | `tools/code_orchestrator.py`（`execute_code_plan`）`tools/__init__.py`（`CODING_TOOLS`） | `test_code_orchestrator.py::TestToolRegistration` |
| 删除 dynamic_discovery / aci_spec | ✅ | 删除 `src/tools/dynamic_discovery.py` `src/tools/aci_spec.py` 及 `tests/unit/test_aci_spec.py`，清理 `test_p2_features.py` 中 `TestToolDiscovery` | 全量回归通过 |

**验收结果**：全量回归 `pytest -q` → **834 passed, 0 failed**（2026-08-20）。
- 新增/修改单测：`test_result_aggregator.py`（脱敏/偏好注入）、`test_v8_expression_agent.py`（偏好注入/降级）、`test_tool_reviewer.py`（复核前置）、`test_code_orchestrator.py`（注册）、`test_server_api.py`（consolidate 端点 + user_id 透传）均通过。
- SSE 测试跨循环泄漏修复：`tests/conftest.py` 新增 autouse fixture 重置 `sse_starlette.sse.AppStatus` 全局单例，解决 "bound to a different event loop"。