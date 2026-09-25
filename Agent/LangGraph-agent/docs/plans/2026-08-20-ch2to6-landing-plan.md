# 第2-6章 × LangGraph-agent 落地改造方案

> 依据《AI Agent 设计原理与工程实践》第2-6章，对照本项目现有实现，形成可落地的分章改造清单与任务拆解。
> 创建日期：2026-08-20

---

## 结论先行

第2/3/6章的成熟度显著高于同量级项目：`ContextCompressor`、`StatusBar`、混合 RAG、语义记忆检索、确定性评估门禁均已对齐教材的"标准答案"式实现。

真正的落地差距集中在四件事：

1. **上下文工程缺少"任务内记忆/条件注入"层**（第2章：任务 plan/progress 未进入上下文）
2. **记忆只有"写入检索"、没有"复盘整合/冲突淘汰"**（第3章：User-as-Code 两阶段的后半段缺失）
3. **工具缺少轻量 Agent 侧运行时，写类工具门控依赖前端 HITL，无服务端独立复核**（第4章）
4. **第5章 Coding Agent 的"错误恢复/自省"几乎是空白的**（用全章唯一弱点）

---

## 落地决策与分阶段执行计划

> **决策档位**
> - **建议纳入**：收益高、风险低、当前业务痛点分明，本轮就做。
> - **暂缓**：有价值但需专门排期/验证，或触及安全信任边界需谨慎。
> - **仅远期**：当前业务不触发，属假设性能力或运维便利，等痛点出现再做。

**为什么不能全部纳入？** 方案文档写的是"理想全集"，落地是按"当前业务痛感 × 风险 × 收益/成本"做的子集。以下三项决定取舍：
1. **当前业务痛点**：当下不痛（知识库小、无外部工具、脚本可信）→ 仅远期。
2. **触及信任边界**：安全/经验沉淀路径宁紧勿松，需充分回归验证 → 暂缓。
3. **收益/成本比**：改动面大或需独立 LLM/框架 → 暂缓，非本轮。

| 章节 | 改造项 | 决策 | 阶段 |
|---|---|---|---|
| 6 | 承诺-行动一致性 + 无证据陈述检查 | **建议纳入** | Phase 1 |
| 5 | code_orchestrator 失败重建 + 保留集校验 | **建议纳入** | Phase 1 |
| 6 | 异源裁判配置 | **建议纳入** | Phase 1 |
| 2 | 状态栏 token/预算显式化 | **建议纳入** | Phase 1 |
| 2 | TaskContext 任务内记忆层 | 暂缓 | Phase 2 |
| 2 | 注入检测分层 | 暂缓 | Phase 2 |
| 4 | 服务端独立复核（tool_reviewer） | 暂缓 | Phase 2 |
| 4 | degraded 语义完善 | 暂缓 | Phase 2 |
| 3 | 经验复盘/整合/淘汰 | 暂缓 | Phase 2 |
| 3 | 经验写入质量 veto | 暂缓 | Phase 2 |
| 6 | Pass@k / 错误归因聚合 | 暂缓 | Phase 2 |
| 3 | RAG 增量 ingest | 仅远期 | Phase 3 |
| 3 | 拆分 user_preferences/analysis_experiences | 仅远期 | Phase 3 |
| 4 | MCP 适配器 | 仅远期 | Phase 3 |
| 5 | 沙箱隔离 | 仅远期 | Phase 3 |
| 6 | 异常/退化注入数据集 | 仅远期 | Phase 3 |

### 分阶段执行计划

- **Phase 1（本轮落地）**：上表"建议纳入"的 4 项，详见【落地实施记录】。
- **Phase 2（后续迭代）**：7 项暂缓项，每项需独立任务单、单测与回归验证后再合并。
- **Phase 3（仅远期）**：5 项，等业务痛点/外部依赖出现时按需触发。

---

## 落地实施记录

> 记录 Phase 1 已落地的代码改动，与下方"差距与落地项"一一对应。

### Phase 1-1 · 第6章 承诺-行动一致性 + 无证据陈述（`tests/eval/checks.py`）
新增 `check_commitment_action`（声称完成的动作须有工具调用背书）与 `check_no_unfounded_claim`（结论性断言须有数据/规则/工具背书），接入 `run_all_checks` 归因顺序。

### Phase 1-2 · 第5章 code_orchestrator 失败重建 + 保留集（`src/tools/code_orchestrator.py`）
为 `CodePlan` 增加 `retention_set`，执行后校验保留键；新增 `execute_plan_with_recovery`，失败/保留集不满足时退化为已验证兜底并标记 `recovered=True`。

### Phase 1-3 · 第2章 状态栏剩余预算（`src/nodes/status_bar.py`）
增加剩余预算显式化，临近上限注入"仅做小结"、耗尽时注入"立即结论"指令。

### Phase 1-4 · 第6章 异源裁判（`.env.example` + `tests/eval/rubric_judge.py`）
增加 `EVAL_JUDGE_MODEL`/`EVAL_JUDGE_API_BASE`/`EVAL_JUDGE_API_KEY` 独立裁判通道，缺失时回退 `OPENAI_*`。

### Phase 1-5 · 回归缺陷修复（`src/nodes/rule_engine.py`）
在回归验证中发现并修复既有失败 `TestRuleEngineNodeIntegration::test_rule_engine_node_v72_queries`：
- **根因**：`_is_complex_query` 的 `分析.*(?:原因|问题|情况)` 宽泛启发式会在规则匹配前拦截
  "分析连纤1中断的原因"，导致 R101/R104 永远无法命中确定性规则。
- **修复**：移除该过宽启发式（R101/R104/R050-R052 已精确覆盖此类分析查询）；
  顿号/连接词/"并+分析类动词"等复合查询检测仍保留。
- **验证**：`test_rule_engine_v72.py` + `test_rule_engine.py` + `test_regression.py::TestRuleEngineNodeIntegration`
  + `test_routing.py` 共 78 passed。

---

## Phase 2 推进记录

> 后续迭代中已落地的"暂缓"项，逐项记录。

### Phase 2-1 · 第3章 经验写入质量 veto（`src/memory/experience_store.py`）
- **实现**：`save()` 新增 `_passes_quality_veto` 门禁，复用 `check_numbers_grounded`
  校验结论中数字能否溯源到自身 evidence，无法溯源（幻觉数字）则拒绝入库。
- **保守性**：结论无数字时放行，避免误伤纯文字结论；良性数字（光纤 ID 等 0-31）不误判。
- **验证**：新增 `TestQualityVeto` 3 例。

### Phase 2-2 · 第2章 TaskContext 任务内记忆层（`src/context/task_context.py`）
- **实现**：新增纯代码派生模块 `task_context.py`；`state.py` 增加 `task_plan`/`task_progress`；
  `intent_router_node` 写任务计划，`result_aggregator_node` 回写已完成步骤；
  `analysis_expert` 在 `{status_bar}` 前注入 `{task_context}`。
- **命名对齐**：计划步骤经 `_PLAN_STEP_ALIASES` 归一化到标准步骤名，保证与进度匹配，
  `_derive_next_step` 正确推断下一步。
- **验证**：新增 `TestTaskPlan`/`TestNextStep`/`TestBuildTaskContext` 7 例。

### Phase 2-3 · 第4章 服务端独立复核 tool_reviewer（`src/security/tool_reviewer.py`）
- **实现**：新增纯代码复核器（零 LLM），对高风险写工具做服务端参数校验；
  校验参数类型白名单、高风险参数约束正则、空参数检查；低风险工具跳过复核。
  decision：allow / block / review。与前端 `confirmation_gate`（HITL）互补。
- **验证**：新增 `TestReviewer` 5 例。

### Phase 2-4 · 第4章 degraded 语义完善（`src/tools/tool_result.py` + `src/nodes/status_bar.py`）
- **实现**：`ToolExecutor.run` 超时归为 degraded（可重试降级，区别于 error）；
  `status_bar` 新增降级工具数统计注入（换渠道/重试提示）。
- **验证**：改写/新增相关单测通过。

### Phase 2-5 · 第2章 注入检测分层（`src/nodes/input_guard.py`）
- **实现**：两层正则分级：第一层 `INJECTION_PATTERNS`（9 条强规则，命中即拦截 `blocked`）；
  第二层 `SUSPICIOUS_PATTERNS`（7 条弱规则，命中仅标记 `injection_suspicion` + `guard_notice`，
  不拦截）。`guard_notice` 注入到 `analysis_expert` 的 LLM prompt 中，供语义级后续校验。
- **状态扩展**：`state.py` 新增 `injection_suspicion`、`guard_notice` 字段。
- **验证**：新增 `TestSuspiciousLayering` 4 例（疑似标记、审计留痕、合法输入不误标、普通查询无标记）。

### Phase 2-6 · 第3章 经验复盘/整合/淘汰（`src/memory/consolidator.py`）
- **实现**：新增 `ExperienceConsolidator` 离线整合器（零 LLM，纯 SQL + Python 确定性操作）。
  整合动作：去重合并（同一 fiber_key 下结论相似的碎片合并，evidence 取并集）、
  过期标记（超过 `stale_days` 标记 stale）、超量淘汰（同 fiber_key 超过上限的旧经验标记 stale）。
- **相似判定**：长度分桶粗筛 → bigram Jaccard 相似度精判（阈值 0.45），避免误合语义不相关的经验。
- **兼容性**：自动为旧表补 `stale` 列（ALTER TABLE），幂等建表。
- **验证**：新增 `test_consolidator.py` 6 例（合并/不合并/过期/超量/dry_run/旧表兼容）。

### Phase 2-7 · 第6章 Pass@k / 错误归因聚合（`tests/eval/`）
- **实现**：
  - 新增 `tests/eval/failure_diagnosis.py`：错误归因聚合（按首个错误检查项统计，回答"哪里先错"）、
    pass@k 无偏估计器（Codex 论文公式）、McNemar 配对显著性检验（旧 vs 新改造对比）。
  - 改写 `e2e_runner.py`：`E2EReport` 新增 `failure_attribution`、`passk` 字段；
    `run_suite` 返回时自动聚合失败归因；新增 `run_suite_passk` 多采样方法。
  - 改写 `run_eval.py`：新增 `--passk` 和 `--passk-samples` 参数；
    Pass@k 模式下用聚合 `pass_at_k` 与基线比较。
  - `format_report` 新增错误归因聚合表和 Pass@k 最薄弱用例输出。
- **验证**：新增 `test_failure_diagnosis.py` 17 例（归因计数/空结果/边界/公式值/McNemar 检验/配对对比）。

> **验证状态**：Phase 2 七项全部落地，`tests/unit` 全量 — 详见"全量回归验证"。

---

## 一、第2章 · 上下文工程

### 已对齐（保持不动）
- **上下文压缩**：`src/memory/context_compressor.py` — 摘要 + 实体提取 + 语素级确定性掏取，`to_injection_text()` 注入后端；已接入 `src/nodes/input_guard.py`（摘要替代滑动窗口）。
- **Agent 状态栏**：`src/nodes/status_bar.py` — 纯代码派生、注入 user 消息末尾、不改 system prompt（KV Cache 友好）。
- **Skills + 渐进披露**：`src/skills/loader.py`（扫描/校验/热加载原子切换）、`src/skills/registries.py`（六个注册表按需拉取）。
- **注入防御**：`src/nodes/input_guard.py`（9 条正则+长度截断，作为 Layer1 首节点）；`src/security/output_filter.py`（按角色脱敏输出）。

### 差距与落地项

| 差距（本书观点） | 落地改造 | 涉及文件 |
|---|---|---|
| 压缩只作用于"会话历史"，未维护**当前任务的 plan/progress**（第2章主张显式维护任务状态） | 新增 `TaskContext` 模块：在 `state` 维护 `task_plan/task_progress/completed_steps`，各阶段写回并注入 prompt | 新增 `src/context/task_context.py`；改 `src/graph/state.py`、`src/graph/main_graph.py` |
| 注入检测只用正则、无分层（本书：正则→LLM 语义分级） | 注入检测分档：`blocked`（确定拦截）/ `suspect`（转人工或降级）/ `pass`（放行），避免误杀合法输入 | 改 `src/nodes/input_guard.py` |
| 状态栏未覆盖 **token/预算**（仅 loop/llm 计数） | 状态栏增加 `remaining_budget`；接近上限时注入"仅做小结，不请求新工具" | 改 `src/nodes/status_bar.py` |
| 压缩摘要无验证与过期 | 为 `ConversationSummary` 增加 `created_at` 与置信度；超过 N 轮后重建摘要 | 改 `src/memory/context_compressor.py` |

---

## 二、第3章 · 记忆与知识库

### 已对齐（保持不动）
- **用户记忆（个性偏好）**：`src/memory/user_memory.py` — 纯规则注入偏好到 ExpressionAgent 输出格式，零 LLM。
- **经验存储与去重**：`src/memory/experience_store.py`（确定性写入、severity 去重）；`src/memory/memory_retriever.py`（精确+语义+混合三路检索，embedding 不可用降级 BM25）。
- **RAG 混合检索**：`src/rag/engine.py` — Vector(0.6) + BM25(0.4)、查询改写、懒加载、缺依赖降级。

### 差距与落地项

| 差距（本书观点） | 落地改造 | 涉及文件 |
|---|---|---|
| "保存≠学习"：只有写入+检索，无**复盘/归纳/淘汰**（第3章 User-as-Code 两阶段后半段） | 新增离线整理任务：周期合并相似 `fiber_key`、标记 `stale`（被新证据推翻 / 长期未用）、补 `evidence_source` 溯源 | 新增 `src/memory/consolidator.py`；接入现有异步/定时任务 |
| 经验写入无质量验证门禁 | 复用 `src/governance/report_checklist.py` 的数字溯源 + 完整性下线做写入前置 veto（`numbers_grounded` 不通过则拒绝入库） | 改 `src/memory/experience_store.py`、`src/memory/memory_retriever.py` 的 `save()`]
| 知识库为手写 markdown + Chroma 一次性建库，无增量 ingest | `src/rag/ingest.py` 增加**增量 upsert**：按文件 mtime 增量，文件变更时重建对应 doc chunk | 改 `src/rag/ingest.py` |
| 用户记忆(第3章)与"行动经验"(第8章) 都压在 `analysis_experiences` 单一表 | 拆分 `user_preferences`（个性，决定怎么表达）与 `analysis_experiences`（行动经验，决定怎么分析），检索时分源 | 改 `src/memory/experience_store.py`、导入方 |

---

## 三、第4章 · 工具、MCP 与安全

### 已对齐（保持不动）
- **工具结构化返回**：`src/tools/tool_result.py` — status/data/raw/error/latency 五元组 + `ToolExecutor`（超时/熔断/JSON 解析）。
- **工具契约描述（ACI）**：`src/tools/aci_spec.py` — 能力声明/schema/风险/副作用/幂等性（"Constraints 编码在工具描述"）。
- **风险分级 + 动态升级 + 确认门禁**：`src/governance/tool_risk.py`（LOW/MED/HIGH + `fiber_count>20`/`scope=all` 动态升级）；`src/tools/confirmation_gate.py`（写操作 HITL：TTL/上限/单次消费）。

### 差距与落地项

| 差距（本书观点） | 落地改造 | 涉及文件 |
|---|---|---|
| 高险操作依赖**前端 confirm**，缺**服务端独立复核**（提案者-审核者分离） | 在 `confirmation_gate.confirm()` 之后、真正执行写工具前插入**服务端审核节点**：独立 LLM 对照 `tool_risk` profile 复核参数与 user 意图是否一致 | 新增 `src/security/tool_reviewer.py`；改调用链 |
| `ToolExecutor` 异常被吞成 error，**degraded 语义未充分使用** | 明确 degraded 触发条件（部分成功/后端部分离线），并入状态栏统计驱动"换渠道/重试/告知" | 改 `src/tools/tool_result.py`、`src/nodes/status_bar.py` |
| 工具为进程内函数，无跨进程/外部工具接入协议（无 MCP） | 引入工具适配器层（到 MCP 或 HTTP），保持 `ToolResult` 契约不变 | 新增 `src/tools/adapters/` |
| 动态风险规则字符串条件硬编码在代码里 | 迁移到 `config/thresholds.yaml`，并加参数白名单校验防注入 | 改 `src/governance/tool_risk.py`、`config/thresholds.yaml` |

---

## 四、第5章 · Coding Agent（代码作为元能力）

### 已对齐（保持不动）
- `src/tools/code_orchestrator.py`：自然语言→代码计划→**AST 静态验证**→**沙箱执行**→结果 schema 校验（"Verification before Execution"）。

### 差距与落地项

| 差距（本书观点） | 落地改造 | 涉及文件 |
|---|---|---|
| 有生成验证，却**缺"错误恢复 + 自我修正闭环"**（第5章最强调） | `code_orchestrator` 增加失败重建：基于失败信息重构代码计划而非单次终止；区分"可重试错误/不可重试错误" | 改 `src/tools/code_orchestrator.py` |
| 只做 AST+结果验证，未对**旧行为保留（retention）**做检查 | 给代码计划增加"必须保留的成功行为用例"集，生成方案不可破坏（保留集+边界集双验证） | 改 `src/tools/code_orchestrator.py` |
| 沙箱仅 `redirect_stdout`+AST，非隔离进程 | 当前内部分析场景标注"已知受限"；若计划运行任意外部代码，升级 subprocess/容器沙箱 + 资源配额 + 文件白名单 | 改 `src/tools/code_orchestrator.py`（可先降级标注） |

---

## 五、第6章 · Agent 评估（最扎实的一块）

### 已对齐（保持不动）
- **确定性检查先行 + 幻觉 veto**：`tests/eval/checks.py`（注入/意图/参数/工具/数字溯源/路径六项；`check_numbers` 复用 `src/governance/report_checklist.py` 一票否决）。
- **LLM 软维度评判其后**：`tests/eval/rubric_judge.py`（factual/completeness/compliance/expression 四维 Rubric，仅对硬门通过者评分）。
- **门禁与退出码**：`scripts/run_eval.py`（1=意图<95%、2=注入拦截<100%、3=幻觉 veto）；`scripts/regression_gate.py`（监测 prompts/skills/thresholds 变更自动跑回归）。

### 差距与落地项

| 差距（本书观点） | 落地改造 | 涉及文件 |
|---|---|---|
| 评估集中在"最终结果"，缺**过程/规则违背**维度（承诺-行动一致性） | 新增 `check_commitment_action`（声称完成是否真的调用写工具）、`check_no_unfounded_claim`（无证据陈述） | 改 `tests/eval/checks.py`、`tests/eval/runner.py` |
| **Rubric 同源裁判**（与被评系统同家族 qwen） | `.env` 的 `EVAL_JUDGE_MODEL` 指向**异源**评判 Key | 改 `.env.example`、`tests/eval/rubric_judge.py` 说明 |
| 只跑一次取 pass_rate，**无 Pass@k / Pass^k** | 关键用例做 fixed-seed 多采样，输出 pass@3，并用配对显著性（McNemar）判断"是否真改善" | 改 `tests/eval/e2e_runner.py`、`scripts/run_eval.py` |
| 基线为直觉比较（pass_rate 下降即红） | 补**错误归因聚合**：按失败检查项统计"首个错误"最多环节，从"过不过"升级为"哪里先错" | 改 `tests/eval/runner.py`、新增 `tests/eval/failure_diagnosis.py` |
| 评估集为固定 QA 用例，**缺异常/退化注入** | 增加异常场景集（后端超时、部分工具自定义、降级路径介入），验证 Harness 兜底质量 | 新增 `tests/eval/adversarial_x.json` |

---

## 落地优先级（改造顺序）

| 优先级 | 改造项 | 对应章节 | 成本 | 关键文件 |
|---|---|---|---|---|
| **P0** | 补"承诺-行动一致性"过程检查 | 6 | 低 | `tests/eval/checks.py` |
| **P0** | `code_orchestrator` 失败重建闭环 + 保留集校验 | 5 | 中 | `src/tools/code_orchestrator.py` |
| **P1** | 服务端独立复核（提案者-审核者）for 高险写工具 | 4 | 中 | 新增 `src/security/tool_reviewer.py` |
| **P1** | 经验写入前加质量 veto（复用 checklist） | 3 | 低 | `memory/experience_store.py` 等 |
| **P1** | 状态栏 token/预算显式化 + 限上停止 | 2 | 低 | `src/nodes/status_bar.py` |
| **P1** | 新增 `TaskContext` 任务内记忆层 | 2 | 中 | 新增 `src/context/task_context.py` |
| **P2** | RAG 增量 ingest | 3 | 中 | `src/rag/ingest.py` |
| **P2** | 动态风险规则外置到 yaml | 4 | 低 | `src/governance/tool_risk.py`、`thresholds.yaml` |
| **P2** | 异源裁判 + Pass@k + 错误归因聚合 | 6 | 高 | `tests/eval/*`、`.env.example` |

---

## 验收标准
每个改造项完成的标准：
1. 单测覆盖（`tests/unit/`）通过；涉及评估的走 `pytest tests/eval/ -q`。
2. `python scripts/regression_gate.py` 退出码 0（prompts/skills/thresholds 变更时）。
3. `python scripts/run_eval.py --e2e` 通过率不低于基线 `data/eval/e2e_baseline.json`。
4. 不引入对 `prompts/`、`skills/` 过程的破坏；如改这两者，必须同步更新回归用例。