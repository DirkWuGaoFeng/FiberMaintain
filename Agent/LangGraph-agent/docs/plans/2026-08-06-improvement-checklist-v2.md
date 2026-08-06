# 改进清单 v2（修正版）

> 日期：2026-08-06 | 状态：已与负责人对齐全部决策
> 本文档**替代** 2026-08-05 会话中产出的初版组件评估报告（该报告存在四处失实，见第 0 节勘误）。
> 所有结论均经过代码核查与 grilling 会话确认，非推测。

---

## 0. 对初版评估的勘误

初版报告有以下失实之处，已在本版修正：

| 初版说法 | 事实 |
|---|---|
| "无 Prompt 注入防护" | `src/nodes/input_guard.py` 已有 9 条中英文注入检测正则，零 LLM、延迟 <1ms |
| "部分节点未用 Structured Output" | `intent_classifier` 与 `analysis_expert` 已在用 `with_structured_output` |
| "长期记忆缺失" | `data/memory.db` + `src/tools/memory_tools.py` 已实现光纤快照长期记忆（颜色变化才写入） |
| "回归测试未形成流程" | `scripts/regression_gate.py` 存在且设计为 pre-commit 门禁，但**未挂载到任何 hook**（这一条是真实的） |

---

## 1. 已确认的项目前提（决策依据）

| 项 | 结论 | 来源 |
|---|---|---|
| 项目定位 | **内部工具**（团队日常使用，内网部署） | Q1=B |
| 会话形态 | 用户**经常跨轮追问**，服务会重启 → 状态持久化是真实需求 | Q2=A |
| 记忆需求 | **故障处理经验**（"光纤 3 上次误报是因为 XX"），供后续分析引用 | Q3=B |
| 评估目标 | 回归门禁 + v7.1/v8 架构对比，**一份标注集双用途** | Q4=A+C |
| LLM 现状 | 主模型已是 `qwen3.6-plus` 走百炼 API（`LLM_PRIMARY_PROVIDER=openai`），次级/兜底走本地 Ollama | .env 核查 |
| 对话历史 | **滑动窗口**：每线程保留最近 10 轮，与 checkpointer 改造同步实施 | Q11=A |

---

## 2. 实施清单

### P0-A：挂载 regression_gate 到 pre-commit

- **现状**：`scripts/regression_gate.py` 已实现（检测 `prompts/`、`skills/`、`config/thresholds` 变更 → 跑 `tests/unit/`），但全项目无任何 hook 引用它
- **动作**：初始化 git pre-commit hook（或 `.pre-commit-config.yaml`）调用该脚本
- **工作量**：约 1 小时
- **验收**：改动 `prompts/` 下文件并 commit 时自动触发单测回归

### P0-B：Checkpointer 持久化 + 滑动窗口（合并实施）

- **现状**：`src/graph/main_graph.py` 的 `_create_checkpointer()` 使用 `MemorySaver`（进程重启丢全部会话状态）；`langgraph-checkpoint-sqlite` 已在依赖中；`CHECKPOINT_DB` 配置已预留
- **动作**：
  1. `_create_checkpointer()` 改用 `SqliteSaver`（选型 SQLite：与 memory.db/local_cache.db 一致，零新增依赖，内网单节点够用）
  2. 同步实现滑动窗口：每线程 messages 保留**最近 10 轮**，写入前裁剪
- **理由**：主模型走百炼 API 计费，历史无限膨胀 = 费用随轮次线性增长，滑动窗口是真实成本问题而非理论问题
- **明确不做**：摘要压缩（7b 生成摘要替代历史）——收益撑不起复杂度，除非未来确认用户依赖 10 轮以前的上下文

### P0-C：E2E QA 标注集（50 条）

- **现状**：`tests/` 下只有后端 mock 数据，无任何 Agent 端到端标注集
- **动作**：
  1. 建立 50 条标注集：9 个 intent 全覆盖 + 边界情况 + 注入对抗用例
  2. 通过标准：intent 分类准确率 100% + 关键数值/ID 保真（复用 `number_validator` 逻辑）
  3. 新增 `make eval` 目标，支持 `AGENT_MODE=v7/v8` 分别执行（v7.1 vs v8 对比）
- **执行时机**：两级门禁——pre-commit 只跑快速单测（零 LLM）；标注集评估在 Prompt 变更后**手动**跑。主模型已切百炼 API，单条 2-5s，全量约 3-5 分钟，手动跑完全可行
- **明确不做**：定时任务/CI 集成——项目无 CI 基建，属过度设计

### P0-D：动态模型路由核查

- **现状**：分层架构已存在（`get_knowledge_llm()` → 本地 7b，intent 分类 → 百炼 API，rule_engine 零 LLM），但未经系统验证
- **动作**：逐节点核查实际调用的 LLM accessor 与 `LLM_CONFIG` 层级定义是否一致，修正错配
- **性质**：实施核查项，非新功能

### P1-A：故障处理经验记忆（确定性触发）

- **动作**：
  1. 在现有 `MemoryStore`（memory.db）上新增**经验表**（fiber_id / 结论 / 证据 / 时间戳），不引入 Mem0
  2. 写入触发：`analysis_expert` 判定 WARNING/CRITICAL 时**确定性写入**（与现有 color 变化才写的去重哲学一致），不用 LLM 自主触发，避免记忆噪声
  3. 检索注入：`analysis_expert` 提示词中注入该光纤的历史经验
- **理由**：系统哲学是"规则优先、LLM 兜底"，影响后续判断的记忆写入必须确定性

### P1-B：pull_call_create 轻量 HITL

- **背景**：`pull_call_create`/`pull_call_cancel` 是真实写操作，"无 HITL"是架构辩护的最弱项
- **动作**：复用前端 `ClarifyCard` 模式，`pull_call_create` 执行前推送确认卡片，用户确认后才真正调用后端
- **收益**：辩护从"解释为什么没有 HITL"升级为"展示写操作风险分级设计"
- **降级方案**（时间不足时）：不改代码，用"写操作风险分级"话术辩护 + 诚实承认为已知 TODO

### P2（条件触发，当前不排期）

| 项 | 触发条件 |
|---|---|
| RAG Reranker | 知识库文档 > 100 篇，或检索命中率出现可观测下降 |
| LangFuse 接入 | 团队出现"需要看 LLM 成本面板"的明确需求（当前前端 Monitor + Trace 瀑布图已覆盖可观测性需要） |
| 标注集扩充到 100+ 条 | 50 条版本稳定运行后 |

---

## 3. 已砍除项（附理由，供辩护引用）

| 砍除项 | 理由 |
|---|---|
| **Mem0** | 重复造轮子：memory.db 基础设施已存在，加一张经验表即可 |
| **MCP 协议** | 封闭系统，工具全部指向自研 C++ 后端，协议零消费者；Skill YAML 已是自研工具注册机制 |
| **Presidio/PII** | 输出方向已有过滤器（IP/端口/堆栈脱敏）；输入方向由 input_guard 覆盖注入场景 |
| **JWT 强制校验** | 内网团队工具，无多用户对外场景 |
| **多 Agent Supervisor** | 渐进复杂度原则；v8 三层架构（lead_router + orchestrator）已作为实验保留 |
| **摘要记忆** | 被滑动窗口方案取代（见 P0-B） |
| **评估框架（RAGAS/DeepEval）** | 自建标注集 + `make eval` 已满足两级门禁需求，框架引入成本高于收益 |

---

## 4. 遗留事实核查项（实施时顺带确认）

1. 前端 Monitor 的 **Token 消耗图表**数据源是否真实填充（主模型已切 API 计费，该数据变为成本关键指标）
2. v7.1 与 v8 在 50 条标注集上的对比基线（P0-C 完成后首次执行）
