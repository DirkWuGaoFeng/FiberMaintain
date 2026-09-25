# 光纤维护 Agent（LangGraph）深度评估报告

> **评估框架**：《AI Agent 设计原理与工程实践》（博杰力 著）全书十章对标
>
> **评估版本**：v7.1-Final / v8（实验架构）
>
> **评估日期**：2026-08-21
>
> **📌 使用说明**：本报告所有代码位置均相对于项目根目录 `LangGraph-agent/`，方便新员工对照源码学习。

---

## 目录

- [一、评估体系分析（tests/eval）](#一评估体系分析testseval)
- [二、系统架构总览](#二系统架构总览)
- [三、逐章对标评估（含代码定位）](#三逐章对标评估含代码定位)
- [四、综合评分](#四综合评分)
- [五、核心亮点（含代码定位）](#五核心亮点含代码定位)
- [六、改进建议](#六改进建议)
- [七、总结](#七总结)
- [附录 A：代码索引速查表](#附录-a代码索引速查表)

---

## 一、评估体系分析（tests/eval）

### 1.1 评估体系已实现的功能

本系统已实现一套**分层评估体系**，包含 7 个文件，对标书中第六章（Agent 的评估）的多个核心概念：

| 文件路径 | 核心类/函数 | 功能 | 对标书中概念 |
|----------|-----------|------|-------------|
| `tests/eval/runner.py` | `EvalRunner` / `CaseResult` / `EvalReport` | 规则层快速评估（零 LLM，日常门禁） | 评估环境、自动化评估 |
| `tests/eval/e2e_runner.py` | `E2ERunner` / `E2EReport` / `E2ECaseResult` | 端到端评估（真实图执行） | 端到端回归、状态验证 |
| `tests/eval/checks.py` | `run_all_checks()` / `first_failure()` + 8 个 check 函数 | 8 类确定性检查器 | 确定性检查先行、失败归因 |
| `tests/eval/rubric_judge.py` | `RubricJudge` | LLM-as-a-Judge 四维评判 | LLM-as-a-Judge、Rubric 评判 |
| `tests/eval/failure_diagnosis.py` | `pass_at_k()` / `mcnemar_pvalue()` / `paired_verdict()` / `aggregate_first_failures()` | 错误归因聚合 + Pass@k + McNemar 显著性 | 失败归因、统计显著性 |
| `tests/eval/qa_dataset.json` | — | 50 条 QA 标注集（含 v8 映射） | 评估数据集设计 |
| `tests/eval/e2e_dataset.json` | — | 30 条端到端测试用例 | 评估环境 + 数据集 |

### 1.2 评估体系详细对标

#### ✅ 已实现（对标书中第六章）

| 书中原则 | 实现状态 | 具体实现（含代码位置） |
|----------|---------|----------------------|
| **分层评估** | ✅ 完整 | 规则层 `tests/eval/runner.py:EvalRunner` → 端到端层 `tests/eval/e2e_runner.py:E2ERunner` → LLM 评判层 `tests/eval/rubric_judge.py:RubricJudge` |
| **确定性检查先行** | ✅ 完整 | `tests/eval/checks.py:run_all_checks()` 8 类检查全部零 LLM，在 `e2e_runner.py:run_case()` 中先行于 Rubric 评判 |
| **数字幻觉 veto** | ✅ 完整 | `tests/eval/checks.py:check_numbers()` → 调用 `src/governance/report_checklist.py:check_numbers_grounded()` 做数字溯源，一票否决 |
| **失败归因（首个错误）** | ✅ 完整 | `tests/eval/checks.py:first_failure()` 定位首个失败检查项 + `tests/eval/failure_diagnosis.py:aggregate_first_failures()` 聚合统计 |
| **Pass@k** | ✅ 完整 | `tests/eval/failure_diagnosis.py:pass_at_k()` 标准无偏估计器（Codex 论文公式）；`tests/eval/e2e_runner.py:run_suite_passk()` 多采样评估 |
| **配对显著性检验** | ✅ 完整 | `tests/eval/failure_diagnosis.py:mcnemar_pvalue()` + `paired_verdict()` McNemar 精确检验（双侧），改造前后对比 |
| **承诺-行动一致性** | ✅ 完整 | `tests/eval/checks.py:check_commitment_action()` 检测 `_COMMITMENT_VERBS`（"已提交/已退款/已执行"等）是否有工具调用背书 |
| **无证据陈述检测** | ✅ 完整 | `tests/eval/checks.py:check_no_unfounded_claim()` 检测 `_DEFINITIVE_MARKERS`（"已经完全解决/彻底解决"等）是否有数据背书 |
| **LLM-as-a-Judge** | ✅ 完整 | `tests/eval/rubric_judge.py:RubricJudge` 四维度（`factual_accuracy`/`completeness`/`compliance`/`expression`）1-4 分；支持异源裁判（`EVAL_JUDGE_MODEL` 环境变量） |
| **评估数据集覆盖** | ✅ 良好 | `tests/eval/qa_dataset.json`（50 条 QA，覆盖 9 种意图）+ `tests/eval/e2e_dataset.json`（30 条 E2E，含注入对抗 + 边界用例） |
| **注入拦截率指标** | ✅ 完整 | 专项注入测试用例（`qa_dataset.json` 中 `INJ-01`~`INJ-05`，`e2e_dataset.json` 中 `E2E-INJ-01`~`E2E-INJ-04`），独立统计拦截率 |
| **延迟指标** | ✅ 完整 | `runner.py:EvalReport.latency_p50/p95` + `e2e_runner.py:E2EReport.latency_p50/p95` |
| **降级路径处理** | ✅ 完整 | `tests/eval/checks.py` 中 `_DEGRADED_PATHS = {"degraded", "blocked"}`，后端离线时检查自动降级为 skip |
| **基线对比** | ✅ 完整 | `tests/eval/runner.py:EvalRunner.compare_with_baseline()` 对比当前与基线，输出 `degradation` 标记 |
| **Markdown 报告生成** | ✅ 完整 | `tests/eval/runner.py:EvalRunner.format_report()` + `tests/eval/e2e_runner.py:E2ERunner.format_report()` |

#### ⚠️ 可改进

| 书中原则 | 现状 | 改进方向 |
|----------|------|---------|
| **轨迹前缀回归** | 未实现 | 截取首个错误之前的状态单独验证（书中 Ch6） |
| **模拟用户评估** | 未实现 | 类似 τ-bench 的渐进式信息透露评估环境 |
| **Rubric 四准则（Scale AI）** | 部分实现 | `RubricJudge` 增加"基于专家指导"+"标准重要性权重"（一票否决项） |
| **古德哈特定律防范** | 未实现 | 评估指标被优化后的偏差检测 |
| **评估驱动模型选型** | 未实现 | 多模型 A/B 对比评估流程 |

### 1.3 评估体系评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 评估基础设施 | ⭐⭐⭐⭐⭐ | 分层评估 + 确定性检查 + 幻觉 veto，对标书中核心概念 |
| 评估数据集 | ⭐⭐⭐⭐ | 覆盖 9 种意图 + 注入对抗，缺少模拟用户评估 |
| 统计方法 | ⭐⭐⭐⭐⭐ | Pass@k + McNemar 显著性 + 错误归因聚合，超出基础要求 |
| LLM-as-a-Judge | ⭐⭐⭐⭐ | 四维度评判 + 异源裁判支持，Rubric 可进一步细化 |
| 评估驱动闭环 | ⭐⭐⭐ | 有基线对比，缺少自动化的"评估→假设→实验→验证"闭环 |

**评估体系总评：⭐⭐⭐⭐ (4.2/5) —— 超出基础要求，具备生产级评估能力**

---

## 二、系统架构总览

| 维度 | 实现 |
|------|------|
| **版本** | v7.1-Final（18节点）+ v8 实验架构（三层） |
| **编排框架** | LangGraph StateGraph |
| **主图入口** | `src/graph/main_graph.py:build_main_graph()` |
| **节点数** | 18（v7.1）/ 5（v8） |
| **LLM 梯度** | 三层配置 → `src/config.py:LLM_CONFIG`；LLM 获取 → `src/llm/provider.py` |
| **工具数** | 23+ REST API 工具，按域分组 → `src/tools/__init__.py` |
| **Skills** | 16 个 YAML Skill → `skills/*.yaml`；加载 → `src/skills/loader.py` |
| **评估用例** | 50 条 QA + 30 条 E2E → `tests/eval/*.json` |
| **后端** | C++ 光纤维护服务（WSL）；HTTP 客户端 → `src/tools/_http_client.py` |
| **前端** | Vue 3 + TypeScript → `frontend/` |

### 核心架构图

```
用户输入
  ↓
input_guard（注入检测 + 上下文压缩）         ← src/nodes/input_guard.py
  ↓
rule_engine（27+ 条正则规则，零 LLM）        ← src/nodes/rule_engine.py:RuleEngine
  ↓
┌─── fast_path ──→ fast_path_executor        ← src/nodes/fast_path_executor.py
│                    ↓
│               result_aggregator → END      ← src/nodes/result_aggregator.py
│
├─── rule_hit_complex ──→ param_gate          ← src/nodes/param_gate.py
│                         ↓
│                    intent_router             ← src/nodes/intent_router.py
│
└─── rule_miss ──→ intent_classifier（14b）   ← src/nodes/intent_classifier.py
                    ↓
               intent_router
                    ↓
     ┌──────────────┼──────────────────┐
     ↓              ↓                  ↓
data_collector   batch_dispatcher   knowledge_qa     ← src/graph/subgraphs/
(ReAct Agent)    ← src/nodes/       ← src/graph/
     ↓            batch_dispatcher.py  subgraphs/
rule_judgment                         knowledge_assistant.py
← src/nodes/rule_judgment.py
     ↓
analysis_expert（14b）                  ← src/nodes/analysis_expert.py
     ↓              ↓
need_more_data   direct_narrate / generate_report
(ReAct loop↑)         ↓
                 narrator（7b）        ← src/nodes/narrator.py
                       ↓
              narrator_validator（零 LLM）  ← src/nodes/narrator_validator.py
                 ↓              ↓
               pass          fail → template_fallback  ← src/nodes/template_fallback.py
                 ↓              ↓
           result_aggregator → END
```

---

## 三、逐章对标评估（含代码定位）

### 📗 第1章：Agent 基础框架 — ⭐⭐⭐⭐⭐ 优秀

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **Agent = LLM + 上下文 + 工具** | 三层LLM + MainGraphState + 23+工具 | LLM: `src/llm/provider.py`；状态: `src/graph/state.py:MainGraphState`；工具: `src/tools/__init__.py` | ⭐⭐⭐⭐⭐ |
| **Harness = 上下文 + 工具 + 约束 + 验证 + 纠正** | 五要素全覆盖（详见下表） | 见 Harness 映射表 | ⭐⭐⭐⭐⭐ |
| **从工作流到自主Agent的光谱** | 混合模式：规则引擎（工作流）+ ReAct循环（自主） | 规则引擎: `src/nodes/rule_engine.py:RuleEngine`；ReAct: `src/graph/subgraphs/data_collector.py` | ⭐⭐⭐⭐⭐ |
| **护栏与安全性** | 多层防御 | 输入: `src/nodes/input_guard.py`；参数: `src/nodes/param_gate.py`；工具: `src/security/tool_reviewer.py`；输出: `src/security/output_filter.py` | ⭐⭐⭐⭐⭐ |

**Harness 五要素映射（含代码位置）：**

| Harness 功能 | 实现组件 | 代码位置 |
|-------------|---------|---------|
| **上下文管理** | MainGraphState、status_bar、task_context、context_compressor | `src/graph/state.py:MainGraphState`；`src/nodes/status_bar.py:build_status_bar()`；`src/context/task_context.py:build_task_context()`；`src/memory/context_compressor.py:ContextCompressor` |
| **工具接口** | 23+ REST 工具、Skill YAML、_http_client | `src/tools/__init__.py`（`DATA_COLLECTOR_TOOLS`/`REPORT_TOOLS`/`KNOWLEDGE_TOOLS`）；`skills/*.yaml`；`src/tools/_http_client.py:FiberHttpClient` |
| **约束** | 注入检测、参数校验、工具复核、人工确认 | `src/nodes/input_guard.py:INJECTION_PATTERNS`；`src/nodes/param_gate.py`；`src/security/tool_reviewer.py:ToolReviewer`；`src/tools/confirmation_gate.py:ConfirmationGate` |
| **验证** | 数字校验、程序化阈值、反思循环、评估检查 | `src/nodes/narrator_validator.py`；`src/skills/judgment_engine.py:JudgmentEngine`；`src/nodes/report_evaluator.py`；`tests/eval/checks.py:run_all_checks()` |
| **纠正** | 模板兜底、降级策略、熔断器 | `src/nodes/template_fallback.py`；`src/nodes/degradation_handler.py`；`src/resilience/agent_circuit_breaker.py:AgentCircuitBreaker` |

---

### 📗 第2章：上下文工程 — ⭐⭐⭐⭐⭐ 优秀

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **KV Cache 友好：静态前缀不变** | analysis_expert 的 system.md 完全静态 | `prompts/analysis_expert/system.md`（无模板变量，纯静态文本） | ⭐⭐⭐⭐⭐ |
| **动态信息追加到末尾** | status_bar 作为 user 消息注入末尾 | `src/nodes/status_bar.py:build_status_bar()` → 注入 user 消息末尾 | ⭐⭐⭐⭐⭐ |
| **使用标准 API 格式** | 全程使用 LangChain Message 体系 | `src/graph/state.py:MainGraphState.messages`（`Annotated[list[BaseMessage], add_messages]`） | ⭐⭐⭐⭐⭐ |
| **提示工程：流程驱动** | 意图分类器 prompt 结构化 | `prompts/lead_agent/intent_classifier.md`（意图类型→参数提取→规则→输出格式） | ⭐⭐⭐⭐ |
| **业务规则细化** | Skill YAML 中 judgment 条件精确到阈值级别 | `skills/spanloss_query.yaml:judgment`；`config/thresholds.yaml`（唯一权威源）→ `src/governance/threshold_engine.py:ThresholdEngine` | ⭐⭐⭐⭐⭐ |
| **Agent Skills 渐进式披露** | 16个 YAML Skill 按意图触发 | `skills/*.yaml` → `src/skills/loader.py`（扫描/解析/注册）；`src/skills/registries.py:TriggerRegistry`（路由匹配） | ⭐⭐⭐⭐ |
| **Agent 状态栏** | `build_status_bar()` 纯代码维护 | `src/nodes/status_bar.py:build_status_bar()` — 循环进度/预算/失败/停滞风险 | ⭐⭐⭐⭐⭐ |
| **上下文压缩** | ContextCompressor 替代滑动窗口 | `src/memory/context_compressor.py:ContextCompressor.compress_if_needed()` — LLM摘要+确定性实体提取 | ⭐⭐⭐⭐⭐ |
| **提示注入防御** | 双层检测 | `src/nodes/input_guard.py:INJECTION_PATTERNS`（强规则，拦截）+ `SUSPICIOUS_PATTERNS`（弱规则，留痕） | ⭐⭐⭐⭐⭐ |
| **指令与数据分离** | system/user/external 三段式 | `prompts/analysis_expert/system.md`（静态角色）+ `prompts/analysis_expert/user.md`（可信数据）+ `prompts/analysis_expert/external.md`（低信任，`<external_content trust="low">`） | ⭐⭐⭐⭐⭐ |

**🔑 新员工必读代码路径（上下文工程）：**

| 主题 | 必读文件 | 关键函数/类 |
|------|---------|------------|
| 状态栏 | `src/nodes/status_bar.py` | `build_status_bar(state)` — 理解如何把隐式状态显式化 |
| 任务上下文 | `src/context/task_context.py` | `build_task_context(state)` — 理解如何从 state 派生任务计划/进度 |
| 上下文压缩 | `src/memory/context_compressor.py` | `ContextCompressor.compress_if_needed()` — 理解摘要压缩替代滑动窗口 |
| 注入防御 | `src/nodes/input_guard.py` | `input_guard_node()` — 理解双层正则检测 |
| 指令分离 | `prompts/analysis_expert/` | `system.md` + `user.md` + `external.md` — 理解三段式信任架构 |
| 状态定义 | `src/graph/state.py` | `MainGraphState` — 理解 40+ 字段的全局状态设计 |

---

### 📗 第3章：用户记忆和知识库 — ⭐⭐⭐⭐ 良好

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **用户记忆层次** | UserMemory + ExperienceStore + MemoryRetriever | `src/memory/user_memory.py:UserMemoryManager`；`src/memory/experience_store.py:ExperienceStore`；`src/memory/memory_retriever.py:MemoryRetriever` | ⭐⭐⭐⭐ |
| **记忆格式** | SQLite WAL 模式 + JSON 偏好 + 版本控制 | `src/memory/user_memory_store.py:UserMemoryStore`（`PRAGMA journal_mode=WAL`） | ⭐⭐⭐⭐ |
| **RAG 混合检索** | ChromaDB 向量(0.6) + BM25 关键词(0.4) | `src/rag/engine.py:RAGEngine.retrieve()` — 混合检索；`src/rag/query_rewriter.py:rewrite_query()` — 查询改写 | ⭐⭐⭐⭐⭐ |
| **知识更新机制** | Consolidator 离线整合 | `src/memory/consolidator.py:Consolidator.consolidate()` — 合并/过期/淘汰 | ⭐⭐⭐⭐⭐ |
| **经验质量门禁** | `_passes_quality_veto()` 数字溯源 | `src/memory/experience_store.py:ExperienceStore._passes_quality_veto()` → 调用 `src/governance/report_checklist.py:check_numbers_grounded()` | ⭐⭐⭐⭐⭐ |
| **智能体化 RAG** | 部分实现：查询改写但无多轮迭代 | `src/rag/query_rewriter.py:rewrite_query()` — 仅单轮改写 | ⭐⭐⭐ |
| **双层记忆架构** | 偏好常驻 + RAG 按需检索 | `src/memory/user_memory.py:UserMemoryManager.inject_preferences()` + `src/rag/engine.py:RAGEngine.retrieve()` | ⭐⭐⭐⭐ |

**🔑 新员工必读代码路径（知识系统）：**

| 主题 | 必读文件 | 关键函数/类 |
|------|---------|------------|
| 用户偏好 | `src/memory/user_memory.py` | `UserMemoryManager.inject_preferences()` — 零 LLM 偏好注入 |
| 经验存储 | `src/memory/experience_store.py` | `ExperienceStore` — 重点看 `_passes_quality_veto()` 质量门禁 |
| 三级检索 | `src/memory/memory_retriever.py` | `MemoryRetriever.query_hybrid()` — 精确→模糊→语义三级检索 |
| 离线整合 | `src/memory/consolidator.py` | `Consolidator.consolidate()` — Bigram Jaccard 相似度合并 |
| RAG 引擎 | `src/rag/engine.py` | `RAGEngine.retrieve()` — 混合检索 + 文档分块 `_chunk_text()` |
| 查询改写 | `src/rag/query_rewriter.py` | `rewrite_query()` — 用 7b 模型改写用户查询 |

---

### 📗 第4章：工具 — ⭐⭐⭐⭐⭐ 优秀

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **工具分类** | 感知/执行/协作/事件 | `src/tools/__init__.py` — `DATA_COLLECTOR_TOOLS`/`REPORT_TOOLS`/`KNOWLEDGE_TOOLS`/`PULLCALL_TOOLS` | ⭐⭐⭐⭐⭐ |
| **ACI 设计原则** | Skill YAML 声明式定义 | `skills/spanloss_query.yaml` — trigger→tool→judgment→template→test_cases | ⭐⭐⭐⭐⭐ |
| **执行安全：提议者-审核者** | ToolReviewer 独立复核 | `src/security/tool_reviewer.py:ToolReviewer` — 三级决策 allow/block/review | ⭐⭐⭐⭐⭐ |
| **沙盒隔离** | 统一 HTTP 客户端 + 弹性工程 | `src/tools/_http_client.py` — `CircuitBreaker`(L61) + `BackpressureController`(L128) + `FiberHttpClient`(L192) | ⭐⭐⭐⭐⭐ |
| **幂等性** | idempotency_key | `src/nodes/batch_dispatcher.py` — `BatchChunkState.idempotency_key` | ⭐⭐⭐⭐ |
| **事件驱动异步架构** | WebSocket 推送 | `src/events/listener.py` + `src/events/router.py` | ⭐⭐⭐⭐ |
| **工具风险评级** | 三级风险 + 动态升级 | `src/governance/tool_risk.py:ToolRiskEngine` — `get_profile()` + `requires_confirmation()` | ⭐⭐⭐⭐⭐ |
| **人在回路（HITL）** | 令牌确认机制 | `src/tools/confirmation_gate.py:ConfirmationGate` — `request()`/`confirm()`（TTL 600s，MAX_PENDING 50） | ⭐⭐⭐⭐⭐ |

**🔑 新员工必读代码路径（工具系统）：**

| 主题 | 必读文件 | 关键函数/类 |
|------|---------|------------|
| 弹性 HTTP 客户端 | `src/tools/_http_client.py` | `FiberHttpClient` — 重点看 `CircuitBreaker` 三态熔断 + `BackpressureController` 背压控制 |
| 工具风险评级 | `src/governance/tool_risk.py` | `ToolRiskEngine.requires_confirmation()` — 三级风险 + 动态参数升级 |
| 工具复核 | `src/security/tool_reviewer.py` | `ToolReviewer` — 提议者-审核者模式的审核侧实现 |
| 人工确认 | `src/tools/confirmation_gate.py` | `ConfirmationGate.request()`/`confirm()` — 令牌机制 |
| Skill 定义 | `skills/spanloss_query.yaml` | 完整示例：触发器→路由→工具→判断→模板→测试用例 |
| Skill 加载 | `src/skills/loader.py` + `src/skills/registries.py` | `TriggerRegistry` — 理解 Skill 如何编译为正则并匹配 |

---

### 📗 第5章：Coding Agent — ⭐⭐⭐ 部分适用

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **代码作为元能力** | 通过 Skill YAML 实现"声明式代码" | `skills/*.yaml` — 声明式定义触发/工具/判断/模板 | ⭐⭐⭐ |
| **代码作为业务规则约束** | judgment 条件编码为可执行校验 | `src/governance/threshold_engine.py:ThresholdEngine.judge_spanloss()` — 阈值判断 | ⭐⭐⭐⭐⭐ |
| **约束优先于指导** | threshold_engine + tool_risk + number_validator | `src/governance/threshold_engine.py` + `src/governance/tool_risk.py` + `src/governance/report_checklist.py` | ⭐⭐⭐⭐⭐ |

---

### 📗 第6章：评估 — ⭐⭐⭐⭐ 良好（详见第一节）

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **分层评估** | 规则层→端到端层→LLM评判层 | `tests/eval/runner.py` → `tests/eval/e2e_runner.py` → `tests/eval/rubric_judge.py` | ⭐⭐⭐⭐⭐ |
| **确定性检查先行** | 8类检查全部零LLM | `tests/eval/checks.py:run_all_checks()` — 在 `e2e_runner.py:run_case()` 中先行于 Rubric | ⭐⭐⭐⭐⭐ |
| **幻觉 veto** | 数字溯源一票否决 | `tests/eval/checks.py:check_numbers()` → `src/governance/report_checklist.py:check_numbers_grounded()` | ⭐⭐⭐⭐⭐ |
| **失败归因** | 首个错误聚合 | `tests/eval/checks.py:first_failure()` + `tests/eval/failure_diagnosis.py:aggregate_first_failures()` | ⭐⭐⭐⭐⭐ |
| **Pass@k** | 无偏估计器 | `tests/eval/failure_diagnosis.py:pass_at_k()` — Codex 论文公式 `1 - C(n-c,k)/C(n,k)` | ⭐⭐⭐⭐⭐ |
| **配对显著性** | McNemar 精确检验 | `tests/eval/failure_diagnosis.py:mcnemar_pvalue()` + `paired_verdict()` | ⭐⭐⭐⭐⭐ |
| **承诺-行动一致性** | 检测虚假承诺 | `tests/eval/checks.py:check_commitment_action()` — `_COMMITMENT_VERBS` 动词列表 | ⭐⭐⭐⭐⭐ |
| **模拟用户评估** | ⚠️ 未实现 | — | ⭐⭐ |
| **轨迹前缀回归** | ⚠️ 未实现 | — | ⭐⭐ |

---

### 📗 第7章：模型后训练 — ⭐⭐⭐ 不涉及

本系统使用预训练模型（Qwen 2.5 系列），未涉及微调。但**三层 LLM 梯度设计**体现了书中"模型选型"的原则：

| 层级 | 配置位置 | LLM 获取 | 模型 | 用途 |
|------|---------|---------|------|------|
| Primary | `src/config.py:LLM_CONFIG["primary"]` | `src/llm/provider.py:get_primary_llm()` | qwen2.5:14b | 意图分类、分析专家、报告生成 |
| Secondary | `src/config.py:LLM_CONFIG["secondary"]` | `src/llm/provider.py:get_secondary_llm()` | qwen2.5:7b | 叙述员、知识问答、查询改写 |
| Tertiary | `src/config.py:LLM_CONFIG["tertiary"]` | `src/llm/provider.py:get_tertiary_llm()` | qwen2.5:3b | 紧急兜底 |

---

### 📗 第8章：持续进化 — ⭐⭐⭐⭐ 良好

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **三层轨迹验证** | 结果验证 + 过程验证 + 质量门禁 | `src/memory/experience_store.py`（结果）+ `src/security/tool_reviewer.py`（过程）+ `src/governance/report_checklist.py`（质量） | ⭐⭐⭐⭐ |
| **四种更新载体** | 知识库 + Prompt + 程序 | 知识库: `src/memory/experience_store.py`；Prompt: `skills/*.yaml`；程序: `src/governance/threshold_engine.py` | ⭐⭐⭐⭐ |
| **安全边界** | 安全机制不可自我修改 | `src/governance/threshold_engine.py` 独立于 Skill；`src/governance/tool_risk.py` 独立于 LLM | ⭐⭐⭐⭐⭐ |
| **经验整合** | Consolidator 离线整合 + 版本控制 | `src/memory/consolidator.py:Consolidator.consolidate()` — 合并相似、淘汰过期 | ⭐⭐⭐⭐ |

---

### 📗 第9章：多模态 — ⭐⭐ 不涉及

本系统为纯文本交互。

---

### 📗 第10章：多 Agent 协作 — ⭐⭐⭐⭐ 良好

| 书中原则 | 本系统实现 | 代码位置 | 评分 |
|----------|-----------|---------|------|
| **多 Agent 协作模式** | v8 三层架构 | `src/v8/agents/collection_agent.py:CollectionAgent` → `src/v8/agents/analysis_agent.py:AnalysisAgent` → `src/v8/agents/expression_agent.py:ExpressionAgent` | ⭐⭐⭐⭐ |
| **上下文隔离** | 子图独立上下文 | `src/graph/subgraphs/data_collector.py`（独立 messages）；`src/graph/subgraphs/knowledge_assistant.py`（独立 messages） | ⭐⭐⭐⭐⭐ |
| **提议者-审核者** | Narrator → NarratorValidator | `src/nodes/narrator.py`（提议者）→ `src/nodes/narrator_validator.py`（审核者） | ⭐⭐⭐⭐⭐ |
| **四重终止保障** | 轮次/预算/无进展/工具熔断 | `src/graph/routing.py:route_after_analysis()` — 四重条件检查 | ⭐⭐⭐⭐⭐ |
| **Loop 工程** | 停滞预警 + 预算显式化 | `src/nodes/status_bar.py:build_status_bar()` — 预算紧张时显式警告 | ⭐⭐⭐⭐⭐ |

**🔑 新员工必读代码路径（多 Agent）：**

| 主题 | 必读文件 | 关键函数/类 |
|------|---------|------------|
| v8 图定义 | `src/v8/graph.py` | `build_v8_graph()` — 5 节点精简架构 |
| Lead Router | `src/v8/lead_router.py` | `LeadRouter` — 意图解析 → ExecutionPlan |
| Orchestrator | `src/v8/orchestrator.py` | `Orchestrator` — 三层 Agent 循环编排 |
| v8 状态模型 | `src/v8/models.py` | `ExecutionPlan` / `V8State` / `AgentResult` |

---

## 四、综合评分

| 章节 | 评分 | 说明 |
|------|------|------|
| 第1章 基础框架 | ⭐⭐⭐⭐⭐ | Harness 五要素全覆盖 |
| 第2章 上下文工程 | ⭐⭐⭐⭐⭐ | 状态栏、KV Cache 友好、指令与数据分离 |
| 第3章 知识库 | ⭐⭐⭐⭐ | RAG 混合检索优秀，经验质量门禁亮点 |
| 第4章 工具 | ⭐⭐⭐⭐⭐ | Skill YAML + ToolReviewer + 弹性 HTTP 客户端 |
| 第5章 代码生成 | ⭐⭐⭐ | 领域专用 Agent，约束优先原则充分体现 |
| 第6章 评估 | ⭐⭐⭐⭐ | 分层评估 + Pass@k + McNemar，超出基础要求 |
| 第7章 后训练 | ⭐⭐⭐ | 不涉及（使用预训练模型），三层梯度设计合理 |
| 第8章 持续进化 | ⭐⭐⭐⭐ | 经验整合有质量门禁 |
| 第9章 多模态 | ⭐⭐ | 不涉及 |
| 第10章 多Agent | ⭐⭐⭐⭐ | 子图隔离 + 提议者-审核者 + 四重终止保障 |

### 综合评分：⭐⭐⭐⭐ (4.2/5) —— 生产级 Harness 工程的优秀实践

---

## 五、核心亮点（含代码定位）

### 🏆 1. 四重终止保障（防无限循环）

```
① 轮次上限（loop_count ≤ 3）
② LLM 预算（llm_call_count ≤ 10）
③ 无进展检测（连续相同动作签名 MD5）
④ 工具熔断（所有工具调用失败）
```

**代码位置：** `src/graph/routing.py:route_after_analysis()` (L144-199) — 四重条件按优先级检查；`src/graph/routing.py:compute_action_signature()` (L285) — 动作签名 MD5 计算

**状态栏配合：** `src/nodes/status_bar.py:build_status_bar()` (L30-109) — 将预算/停滞风险显式注入 prompt

---

### 🏆 2. 叙述校验器（Narrator Validator）

- 零 LLM 调用的程序化验证（< 1ms）
- 四条验证规则：数值一致、颜色匹配、无幻觉告警、严重程度一致
- 验证失败→模板兜底（非 LLM 重试）

**代码位置：** `src/nodes/narrator_validator.py` — `narrator_validator_node()` 四条规则逐一检查

**模板兜底：** `src/nodes/template_fallback.py` — 验证失败时直接渲染结构化文本

---

### 🏆 3. 状态栏（Status Bar）

```python
# src/nodes/status_bar.py:build_status_bar() 输出示例
- 循环进度: 第 2/3 轮, LLM 调用 5/10, 剩余预算 5 次
- ⚠ 预算紧张（剩 5 次 LLM 调用）: 仅做最终小结
- 已请求数据的工具: fiber_spanloss_query, alarm_query
- 已失败操作: 无
- 已收集数据: 可用（摘要 1234 字符）
- ⚠ 停滞警告: 已连续 1 轮相同动作未获新信息
```

**代码位置：** `src/nodes/status_bar.py:build_status_bar()` — 纯代码派生，零 LLM

---

### 🏆 4. 经验质量门禁

**代码位置：** `src/memory/experience_store.py:ExperienceStore._passes_quality_veto()` — 调用 `src/governance/report_checklist.py:check_numbers_grounded()` 验证结论中的数字能否溯源到证据

---

### 🏆 5. 三层 LLM 梯度

| 层级 | 配置 | LLM 获取 |
|------|------|---------|
| Primary (14b) | `src/config.py:LLM_CONFIG["primary"]` (L80-91) | `src/llm/provider.py:get_primary_llm()` (L78) |
| Secondary (7b) | `src/config.py:LLM_CONFIG["secondary"]` (L93-104) | `src/llm/provider.py:get_secondary_llm()` (L93) |
| Tertiary (3b) | `src/config.py:LLM_CONFIG["tertiary"]` (L105-112) | `src/llm/provider.py:get_tertiary_llm()` (L107) |

各节点的 LLM 选择通过专用函数获取：`src/llm/provider.py` — `get_intent_llm()` / `get_analysis_llm()` / `get_narrator_llm()` / `get_data_collector_llm()` 等

---

### 🏆 6. 提示注入双层防御

| 层级 | 代码位置 | 处理 |
|------|---------|------|
| 强规则 | `src/nodes/input_guard.py:INJECTION_PATTERNS` (L35-45) | 命中即拦截，返回 `processing_path="blocked"` |
| 弱规则 | `src/nodes/input_guard.py:SUSPICIOUS_PATTERNS` (L51-58) | 标记疑似，写入 `injection_suspicion` + `guard_notice` |

---

### 🏆 7. HTTP 客户端弹性工程

**代码位置：** `src/tools/_http_client.py`

| 组件 | 类名 | 行号 | 功能 |
|------|------|------|------|
| 三态熔断器 | `CircuitBreaker` | L61 | CLOSED→OPEN（连续失败≥5次）→HALF_OPEN（冷却30s）→CLOSED |
| 背压控制器 | `BackpressureController` | L128 | 20条滑动窗口，错误率>10%时线性增加延迟 |
| HTTP 客户端 | `FiberHttpClient` | L192 | 统一调用后端，超时分级（2s/3s/5s/10s），4xx/5xx 差异化处理 |

---

### 🏆 8. 评估体系（tests/eval）

| 组件 | 文件 | 核心功能 |
|------|------|---------|
| 8 类确定性检查 | `tests/eval/checks.py` | `run_all_checks()` — 注入/意图/参数/工具/数字/路径/承诺-行动/无证据陈述 |
| LLM 评判 | `tests/eval/rubric_judge.py:RubricJudge` | 四维 1-4 分，支持异源裁判 |
| 错误归因 + Pass@k | `tests/eval/failure_diagnosis.py` | `aggregate_first_failures()` + `pass_at_k()` + `mcnemar_pvalue()` |
| 端到端运行器 | `tests/eval/e2e_runner.py:E2ERunner` | 真实图执行 + `run_suite_passk()` 多采样 |

---

## 六、改进建议

### 🔴 高优先级

| # | 问题 | 建议 | 参考起点 |
|---|------|------|---------|
| 1 | **模拟用户评估** | 实现类似 τ-bench 的渐进式信息透露评估 | `tests/eval/e2e_runner.py` 为基础扩展 |
| 2 | **上下文感知检索** | 在分块前用 LLM 生成前缀摘要 | `src/rag/engine.py:RAGEngine._chunk_text()` (L150) |
| 3 | **Skill 按需发现** | 实现"元数据目录 + 按需加载正文" | `src/skills/registries.py:TriggerRegistry` |

### 🟡 中优先级

| # | 问题 | 建议 | 参考起点 |
|---|------|------|---------|
| 4 | **Cross-Encoder 重排序** | RAG 检索后增加精排 | `src/rag/engine.py:RAGEngine.retrieve()` (L188) |
| 5 | **轨迹前缀回归** | 截取首个错误前的状态单独验证 | `tests/eval/checks.py:first_failure()` |
| 6 | **Memory 版本化冲突检测** | 增加 ADD/UPDATE/DELETE 决策逻辑 | `src/memory/experience_store.py` |
| 7 | **Rubric 细化** | 增加 Scale AI 四准则 | `tests/eval/rubric_judge.py:RUBRIC_PROMPT` |
| 8 | **评估驱动闭环** | "评估→假设→实验→验证"自动化 | `tests/eval/runner.py:compare_with_baseline()` |

### 🟢 低优先级

| # | 问题 | 建议 | 参考起点 |
|---|------|------|---------|
| 9 | **规则引擎外置** | 迁移到 `config/rules.yaml` | `src/nodes/rule_engine.py:RULES` (L62-314) |
| 10 | **可观测性仪表板** | 增加 Langfuse 集成 | `src/observability/` |
| 11 | **v8 架构稳定化** | 稳定后合并到主架构 | `src/v8/graph.py` |
| 12 | **误拒绝测试** | 增加合法输入不被误拦截的测试 | `tests/eval/qa_dataset.json` 新增 `category: "legitimate_sensitive"` |

---

## 七、总结

### 核心设计理念

本系统体现了三个核心工程哲学：

1. **确定性优先**：能用规则/代码解决的不用 LLM
   - 规则引擎 → `src/nodes/rule_engine.py:RuleEngine`（<10ms，零 LLM）
   - 程序化阈值判断 → `src/skills/judgment_engine.py:JudgmentEngine`（零 LLM）
   - 状态栏 → `src/nodes/status_bar.py:build_status_bar()`（零 LLM）
   - 叙述校验 → `src/nodes/narrator_validator.py`（<1ms，零 LLM）

2. **多层防御**：每一层都有独立的安全保障
   - 输入守卫 → `src/nodes/input_guard.py`
   - 参数门禁 → `src/nodes/param_gate.py`
   - 工具复核 → `src/security/tool_reviewer.py:ToolReviewer`
   - 数字校验 → `src/nodes/narrator_validator.py`
   - 输出过滤 → `src/security/output_filter.py:OutputFilter`

3. **弹性工程**：每一步失败都有退路
   - 熔断器 → `src/tools/_http_client.py:CircuitBreaker`
   - 降级处理 → `src/nodes/degradation_handler.py`
   - 模板兜底 → `src/nodes/template_fallback.py`
   - 四重终止 → `src/graph/routing.py:route_after_analysis()`

### 最需要补强的三个方面

1. **模拟用户评估** → 在 `tests/eval/` 中实现类似 τ-bench 的评估环境
2. **上下文感知检索** → 在 `src/rag/engine.py` 中增加前缀摘要生成
3. **Skill 按需发现** → 在 `src/skills/` 中实现渐进式披露

---

## 附录 A：代码索引速查表

按**书中章节**组织的代码位置索引，方便新员工按主题学习。

### 第1章：Agent 基础框架

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| Agent 核心公式 | `src/graph/main_graph.py` | `build_main_graph()` — 18节点主图 |
| Harness 五要素 | 见第三章映射表 | — |
| ReAct 循环 | `src/graph/subgraphs/data_collector.py` | `data_collector_subgraph()` — 使用 `create_react_agent` |
| 四重终止 | `src/graph/routing.py` | `route_after_analysis()` |
| 编排模式 | `src/graph/main_graph.py` | 工作流（rule_engine）+ 自主（data_collector） |

### 第2章：上下文工程

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| 状态定义 | `src/graph/state.py` | `MainGraphState` — 40+ 字段 |
| 状态栏 | `src/nodes/status_bar.py` | `build_status_bar()` |
| 任务上下文 | `src/context/task_context.py` | `build_task_context()` |
| 上下文压缩 | `src/memory/context_compressor.py` | `ContextCompressor.compress_if_needed()` |
| 注入防御 | `src/nodes/input_guard.py` | `INJECTION_PATTERNS` + `SUSPICIOUS_PATTERNS` |
| 指令分离 | `prompts/analysis_expert/` | `system.md` + `user.md` + `external.md` |
| KV Cache 友好 | `prompts/analysis_expert/system.md` | 完全静态，无模板变量 |
| Skill 系统 | `skills/*.yaml` → `src/skills/loader.py` | `SkillDefinition` → `TriggerRegistry` |
| 提示词管理 | `prompts/` | 按角色分目录，Markdown 模板 |

### 第3章：用户记忆和知识库

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| 用户偏好 | `src/memory/user_memory.py` | `UserMemoryManager.inject_preferences()` |
| 偏好存储 | `src/memory/user_memory_store.py` | `UserMemoryStore`（SQLite WAL） |
| 经验存储 | `src/memory/experience_store.py` | `ExperienceStore` + `_passes_quality_veto()` |
| 三级检索 | `src/memory/memory_retriever.py` | `query_hybrid()` — 精确→模糊→语义 |
| 离线整合 | `src/memory/consolidator.py` | `Consolidator.consolidate()` |
| RAG 引擎 | `src/rag/engine.py` | `RAGEngine.retrieve()` + `_chunk_text()` |
| 查询改写 | `src/rag/query_rewriter.py` | `rewrite_query()` |
| 阈值配置 | `config/thresholds.yaml` → `src/governance/threshold_engine.py` | `ThresholdEngine` 唯一权威源 |

### 第4章：工具

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| 工具分组 | `src/tools/__init__.py` | `DATA_COLLECTOR_TOOLS` / `REPORT_TOOLS` / `KNOWLEDGE_TOOLS` |
| HTTP 客户端 | `src/tools/_http_client.py` | `FiberHttpClient` + `CircuitBreaker` + `BackpressureController` |
| 工具风险评级 | `src/governance/tool_risk.py` | `ToolRiskEngine.requires_confirmation()` |
| 工具复核 | `src/security/tool_reviewer.py` | `ToolReviewer` |
| 人工确认 | `src/tools/confirmation_gate.py` | `ConfirmationGate.request()`/`confirm()` |
| Skill YAML | `skills/*.yaml` | `SkillDefinition` schema → `src/skills/schema.py` |
| 事件监听 | `src/events/listener.py` + `src/events/router.py` | WebSocket 推送 |

### 第5章：代码作为约束

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| 阈值引擎 | `src/governance/threshold_engine.py` | `ThresholdEngine.judge_spanloss()` |
| 数字溯源 | `src/governance/report_checklist.py` | `check_numbers_grounded()` |
| 工具风险 | `src/governance/tool_risk.py` | `ToolRiskEngine` |
| 成本追踪 | `src/governance/cost_tracker.py` | `CostTracker` |

### 第6章：评估

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| 快速评估 | `tests/eval/runner.py` | `EvalRunner.run_suite()` |
| 端到端评估 | `tests/eval/e2e_runner.py` | `E2ERunner.run_suite()` / `run_suite_passk()` |
| 确定性检查 | `tests/eval/checks.py` | `run_all_checks()` — 8 类检查 |
| LLM 评判 | `tests/eval/rubric_judge.py` | `RubricJudge.judge()` |
| 错误归因 | `tests/eval/failure_diagnosis.py` | `aggregate_first_failures()` |
| Pass@k | `tests/eval/failure_diagnosis.py` | `pass_at_k()` |
| 配对显著性 | `tests/eval/failure_diagnosis.py` | `mcnemar_pvalue()` + `paired_verdict()` |
| QA 数据集 | `tests/eval/qa_dataset.json` | 50 条，覆盖 9 意图 + 注入 |
| E2E 数据集 | `tests/eval/e2e_dataset.json` | 30 条，含边界用例 |

### 第8章：持续进化

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| 经验写入 | `src/memory/experience_store.py` | `_passes_quality_veto()` 质量门禁 |
| 经验整合 | `src/memory/consolidator.py` | `consolidate()` — 合并/过期/淘汰 |
| 安全边界 | `src/governance/threshold_engine.py` | 独立于 Skill，不可被 LLM 修改 |

### 第10章：多 Agent

| 概念 | 代码位置 | 关键入口 |
|------|---------|---------|
| v8 图 | `src/v8/graph.py` | `build_v8_graph()` — 5 节点 |
| Lead Router | `src/v8/lead_router.py` | `LeadRouter.resolve()` |
| Orchestrator | `src/v8/orchestrator.py` | `Orchestrator.execute()` |
| Collection Agent | `src/v8/agents/collection_agent.py` | `CollectionAgent` |
| Analysis Agent | `src/v8/agents/analysis_agent.py` | `AnalysisAgent` |
| Expression Agent | `src/v8/agents/expression_agent.py` | `ExpressionAgent` |
| v8 状态 | `src/v8/models.py` | `ExecutionPlan` / `V8State` / `AgentResult` |
| 提议者-审核者 | `src/nodes/narrator.py` → `src/nodes/narrator_validator.py` | 叙述 → 校验 |
| 子图隔离 | `src/graph/subgraphs/` | `data_collector.py` / `knowledge_assistant.py` |

---

> **本报告由 AI 辅助生成，基于《AI Agent 设计原理与工程实践》（博杰力 著）全书框架对标分析。**
>
> **📌 新员工建议阅读顺序**：附录 A（代码索引）→ 第五章核心亮点 → 第三章逐章对标 → 选一个模块深入源码阅读。
