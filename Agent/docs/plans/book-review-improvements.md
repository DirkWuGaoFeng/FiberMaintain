# Agent 书籍对照评审与改进施工单

> 依据：`e:\Work\ai-agent-book\book`（重点章节 1/2/3/4/6/8/10）
> 对象：`Agent/LangGraph-agent`（v7.1 主图 + v8 实验架构，横切改进）
> 状态：**第一批（A/B/D）已实施完成**（2026-08-14），验证：单测 458 通过、ruff 通过、
> 提示词模板渲染验证通过。C/E/F/G/H 仍为后续批次候选

---

## 1. 书籍核心要点总结

**核心公式**：Agent = LLM + 上下文 + 工具 = Model + Harness。
Harness 的职责：构建上下文 → 约束动作 → 验证结果 → 纠正错误。
工程范式演进：提示工程 → 上下文工程 → Harness 工程 → Loop 工程 → Graph 工程。

### Ch1 Harness 基础
- 控制骨架：`decision = Model(context)` → `constrain` → `apply` → `verify` → 通过则追加轨迹，否则 `correct`
- 三原则：保持简单、保持透明、ACI（Agent-Computer Interface）防呆设计
- 护栏分输入/执行/输出三侧；超失败阈值、高风险操作触发人工介入

### Ch2 上下文工程
- **KV Cache 三原则**：① 系统提示词/工具定义定下后不改 ② 动态信息永远追加到末尾 ③ 使用标准消息格式，不自拼文本
- **Agent Skills 渐进式披露**：元数据目录常驻 → 正文按需加载 → 子文档深入；description 即路由条件
- **状态栏**：把隐式状态提炼为显式知识，以代码（非 LLM）维护，注入轨迹末尾
- **上下文压缩**：保留优先级 = 架构决策 > 变更记录 > 验证状态 > TODO > 工具输出；上下文感知压缩优于盲目摘要；**隔离优于压缩**（子 Agent 只回传任务描述 + 结论）

### Ch3 用户记忆与知识库
- 记忆生命周期：提取候选 → 来源/策略核验 → 更新；提取器不得自行把未核验字符串当事实
- RAG 流水线：分块 → 稠密 + 稀疏并行检索 → 融合 → **神经重排序（rerank）** → 生成
- **上下文感知检索**：索引期为 chunk 生成上下文前缀再入库，检索失败率可降 49%~67%
- 知识更新 = PR 流程 + 异源 Proposer-Reviewer 审核；索引是可重建的派生物
- 双层记忆：结构化概览常驻上下文 + 原始细节按需检索
- 度量：recall@k / MRR / nDCG

### Ch4 工具
- 五类工具：感知 / 执行 / 协作 / 用户沟通 / 事件触发
- 工具描述三要素：何时用、边界（做不到什么）、具体参数示例；选错工具先查描述而非换模型
- **参数保真**：禁止静默输入转换与静默参数注入
- 执行工具安全分层：输入验证 → 权限控制 → 事前审批（异源模型）→ Sidecar → 沙盒
- **幂等性**：唯一标识去重或先查询后变更；不可幂等操作走"预检-确认"两段式
- 工具过多 → 层次化组织、按需发现、Skills 渐进披露

### Ch6 评估（本项目最薄弱处）
- 评估对象 = **模型 + Harness 组合体**；模型替换实验区分瓶颈在模型还是 Harness
- Pass@k = 能力上限（技术奇观）；Pass^k = 业务可靠性（一次都不能错）
- Rubric 四准则：专家指导、全面覆盖（含陷阱）、权重与一票否决、自包含；**幻觉是一票否决项**
- **确定性检查先行、LLM 评判其后**；失败归因定位**首个错误**步骤
- 端到端回归任务 + 轨迹前缀边界任务（答案 = 可接受动作集合）
- 统计显著性：配对分析、多种子、分差须超噪声带
- **可观测性回流**：生产失败轨迹 → 脱敏 → 沉淀为评估集（活资产）
- 每轮只改一个变量；先检查评测系统本身再动 Agent
- 成本优化（稳定前缀 + 压缩）必须合起来实测，节省比例不能相加

### Ch8 持续进化
- 保存经历 ≠ 学习；学习 = 系统主动完成"评价、对照、归纳、验证"
- **三层验证硬门**：结果验证（环境真值）→ 过程验证（权限/动作序列）→ 质量验证（Rubric）；前两层不通过则拒绝作为学习样本
- 四种更新载体按表示性质路由：事实→知识库；语境规则→Prompt/Skill；确定性/硬安全→程序/Harness；高维隐式→参数
- 发布协议：candidate → boundary_set → retention_set → safety_set → canary → promote/rollback
- 安全边界：证据与指令隔离；安全机制不可自我修改

### Ch10 多 Agent
- 唯一价值判据：**协作过程是否引入新信息**（执行反馈/视觉反馈/工具反馈才有效）
- **同一模型自我审查通常无效甚至有害**；等计算量辩论与单 Agent 持平
- Manager 配最强模型（Plan-and-Act）；步骤预算感知（Manager 按复杂度动态分配预算）
- Proposer-Reviewer：审核者必须读独立证据，能力相近、家族不同
- 失败模式：并发冲突、错误级联、循环失控、理解债

---

## 2. 本地实现对照结论

### 已符合书中原则的设计（保持）

| 本地实现 | 对应原则 |
|---|---|
| `rule_engine` / `rule_judgment` / `fast_path_executor` 零 LLM 确定性优先 | Ch8 确定性/硬约束进程序 |
| `narrator_validator` 数字幻觉确定性校验 | Ch6 确定性检查先行 |
| `experience_store` 确定性写入 + 去重，禁止 LLM 自写记忆 | Ch8 安全边界、Ch3 提取核验 |
| 四重终止保障（轮次 ≤3、LLM 预算 ≤10、无进展检测、工具熔断） | Ch10 循环失控防护 |
| 三层 LLM 梯度（primary/secondary/tertiary）+ 降级链 + 熔断器 | Ch6 分层模型选型 |
| RAG 混合检索（ChromaDB 0.6 + BM25 0.4） | Ch3 混合检索骨架 |
| `confirmation_gate` 两段式确认（pullcall） | Ch4 幂等性/预检确认 |
| `prompts/` 唯一管理点 + `run_regression.py` 提示词回归 | Ch6 提示词版本回归 |

### 已识别差距（A–H，采纳状态见 §3）

| # | 差距 | 书的依据 |
|---|---|---|
| A | 评估体系单薄：仅测 v8 规则匹配层，无端到端轨迹评估、无 Rubric、traces 未回流 | Ch6 |
| B | `report_evaluator` 是同家族 LLM 自我审查，判定逻辑脆弱（字符串启发式） | Ch10 / Ch6 |
| C | RAG 缺 rerank 与上下文前缀，无 recall@k 度量 | Ch3 |
| D | 状态栏不完整：缺失败工具清单、上轮动作签名、已收集数据清单 | Ch2 |
| E | KV Cache 友好性未系统审查（prompt 组装点） | Ch2 |
| F | 23+ 工具描述缺"何时用/边界/示例"系统性审查 | Ch4 |
| G | 经验写入无三层验证门，无过期整理 | Ch8 |
| H | v7.1/v8 双轨维护成本 | Ch1 保持简单 |

---

## 3. 已确认决策（grilling 轮次记录）

### 第一轮
- **Q1 交付形态**：(c) 先出报告文档，确认后逐项实施 ← 本文件
- **Q2 目标架构**：(c) 横切改进为主（两架构共用），H（v7/v8 收敛）单独延后决策
- **Q3 资源约束**：(c) 评估环节允许 API（异源裁判），线上推理保持现状
- **Q4 第一批**：A（评估体系强化）+ B（评估器去自我审查）+ D（状态栏）

### 第二轮
- **Q5 报告范围**：(b) 完整版施工单，落 `Agent/docs/plans/book-review-improvements.md`
- **Q6 A 实施口径**：(a) 确定性检查 + LLM Rubric 评判 + bad case 回流，三件齐做，数据集 ~30 条
- **Q7 B 改造方式**：(b) 确定性清单为主 + LLM 仅评表达质量低权重，确定性失败即 veto
- **Q8 D 实施范围**：(a) 仅 analysis_expert 单点先行，跑通再推广

---

## 4. 实施方案

### A. 评估体系强化

**现状事实**：
- `tests/eval/runner.py` 只测 `LeadRouter._rule_match`（零 LLM 规则匹配）+ 注入检测 + 参数保真
- `data/traces/` 有 300+ 条轨迹 JSON：含 trace_id、user_input、processing_path、status、spans（含 error 字段）、final_output、phase_breakdown
- primary 层已配置为百炼 openai provider（`LLM_PRIMARY_PROVIDER=openai`），API 通道现成

**改动清单**：

1. **新增 `tests/eval/e2e_dataset.json`**（~30 条端到端用例，与现有 `qa_dataset.json` 规则层用例并存）
   - 覆盖：正常数据查询、故障分析（含 severity 断言）、知识问答、批量查询、
     注入攻击、参数缺失需澄清、报告生成、降级场景、轨迹前缀边界用例
     （如"用户纠正先前参数"、"高风险操作前需确认"）
   - 每条用例字段：`id / input / expected_intent / expected_params / expected_tools（可接受工具集合）/ expected_severity / rubric_focus / category`

2. **新增 `tests/eval/e2e_runner.py`**：调用编译后主图（`get_graph()`）真实执行每条用例，
   以独立 thread_id 隔离；记录完整轨迹供评分

3. **新增 `tests/eval/checks.py`（确定性检查器，先行于 LLM）**：
   - `check_intent`：意图与预期一致
   - `check_injection`：注入类用例必须被拦截
   - `check_params`：参数保真
   - `check_tools`：实际调用工具 ⊆ 可接受集合，且无重复冗余调用（路径效率）
   - `check_numbers`：复用 `governance/number_validator` 逻辑，报告/回复中数字须有工具返回支撑（幻觉 veto）
   - `check_status`：最终状态与预期一致（含澄清/降级路径）

4. **新增 `tests/eval/rubric_judge.py`（LLM Rubric 评判）**：
   - 裁判模型：百炼 `qwen3-max`（新增 `EVAL_JUDGE_MODEL` 环境变量，默认 qwen3-max；
     Key 走现有 `OPENAI_API_KEY`/`DASHSCOPE_API_KEY` 通道，**不写入任何文档**）
   - ⚠️ 已知限制：线上 primary 亦为 qwen 家族，不满足 Ch6"异源评判"理想态；
     缓解 = 确定性检查为硬门、LLM 仅评表达与完整性维度；后续如有 GPT/Claude Key 再换异源
   - Rubric 维度（每项 1-4 分，附证据引用）：事实准确性 / 完整性 / 合规性（结论与 severity 一致）/ 表达质量
   - 幻觉 veto：`check_numbers` 失败 → 整条用例直接判 fail，不进 Rubric

5. **新增 `scripts/harvest_badcases.py`**：扫描 `data/traces/`，筛出
   `status != SUCCESS` / `processing_path` 异常 / spans 含 error / 耗时异常 的轨迹，
   输出候选清单（含 trace_id 与原始输入），人工标注后按格式追加进 e2e_dataset.json

6. **门禁扩展 `scripts/regression_gate.py`**：
   - 保留：intent_accuracy ≥ 0.95、injection_block_rate = 1.0
   - 新增：e2e_pass_rate ≥ 基线（首跑建立基线后不得下降）、幻觉 veto 触发数 = 0

**验收标准**：`python scripts/run_eval.py --e2e` 一条命令出 Markdown 报告（确定性指标表 + Rubric 分布 + 失败归因首个错误步骤）；30 条用例在本地跑完 ≤ 15 分钟。

### B. report_evaluator 去自我审查

**现状事实**：
- `src/nodes/report_evaluator.py`：纯 LLM（与生成器同为 primary 层 qwen），
  passed 判定是 `"问题" not in content` 这类字符串启发式，脆弱
- 可对照的数据：`collected_data_summary`、`rule_judgment`、`report_content` 均在 state 中

**改动清单**：

1. **新增 `src/governance/report_checklist.py`**（确定性清单，代码实现）：
   - `numbers_grounded`：报告中出现的数值必须能在 collected_data_summary / rule_judgment 中找到来源（复用 number_validator）
   - `sections_present`：按报告模板（fault_report / daily_report）检查必填章节齐全
   - `severity_consistent`：结论严重级别与 rule_judgment 判定一致
   - 返回 `{check: bool, evidence: str}` 结构
2. **改造 `report_evaluator_node`**：
   - 先跑确定性清单；**任一项失败 → 直接 `passed=False`**（veto），feedback 附具体失败项与证据（供 report_generator 定向修正）
   - 清单全过后，LLM 仅评"表达质量"单维度（低权重）：只有表达质量明确不合格才 refine
   - LLM 调用失败时：以确定性清单结果为准（不再 force pass 掩盖问题，但清单全过则放行）
3. **prompt 调整**：在 `prompts/report_generator/` 中补充"修正指引"说明，使 refine 轮能消费结构化 feedback

**验收标准**：构造 3 个注入数字错误的报告样本，清单必须拦截；正常报告不被误杀；
evaluator 输出 feedback 可定位到具体失败项（不再是模糊整段文本）。

### D. analysis_expert 状态栏

**现状事实**：
- `prompts/analysis_expert/user.md` 末尾已有一行状态：
  `## 状态: 第 {loop_count}/{max_loops} 轮, LLM调用 {llm_calls}/{max_llm_calls}`
- 缺失：已收集数据清单、已失败工具、上轮动作签名（无进展检测依据）

**改动清单**：

1. **新增 `src/nodes/status_bar.py`**：纯代码函数 `build_status_bar(state) -> str`，
   从 state 派生：
   - 已收集数据条目清单（工具名 + 关键结果摘要，不含全文）
   - 已失败工具及原因（来自 collected_data_summary 的 errors）
   - 上一轮 action_signature 与 no_progress_count
   - 剩余循环/LLM 预算
2. **改 `prompts/analysis_expert/user.md`**：将末尾单行状态替换为状态栏区块
   `{status_bar}`（保持"追加在消息末尾"原则，不动 system prompt → 不破坏前缀缓存）
3. **改 `analysis_expert_node`**：注入 status_bar 变量；同步更新 `_USER_KEEP_VARS`

**验收标准**：单测覆盖 build_status_bar 各字段；ReAct 第 2 轮起 LLM 可见失败工具清单；
system prompt 内容零改动（E 项的前置约束）。

---

## 5. 验证路线（每项改动的最小验证）—— 已执行

| 项 | 验证结果 |
|---|---|
| D | test_status_bar.py 11 通过；system prompt 零模板变量（KV Cache 前缀稳定）；顺带修复 rag_context / conversation_summary 两处上下文注入缺失 |
| B | test_report_checklist.py 15 通过（含幻觉 veto 零 LLM、LLM 失败容错、日期负数误提修复） |
| A | test_eval_checks.py 24 通过；harvest_badcases.py 首跑挖出 442 条候选；run_eval.py --e2e/--rubric 就绪 |
| 合流 | tests/unit/ 全量 458 通过；ruff 目标文件全部通过 |

【发现的新问题】规则层快速评估（tests/eval/runner.py）自身基线失败：
INJ-01 未被 v8 规则层拦截、KQ/CC 类无法命中规则匹配 —— 属存量问题，
恰验证了端到端评估的必要性，列入后续批次（修复 v8 security/rule_match 或调整该层预期）。

实施状态：**D/B/A 已完成**（D 已实现状态栏；B 已改造 report_evaluator；A 已建立端到端评估体系）。

---

## 6. 暂缓与后续批次

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| C | RAG rerank + 上下文前缀 + recall@k | 第二批候选 | 依赖 A 建好的评估闭环来验收 |
| E | KV Cache 前缀审查 | 第二批候选 | D 已确立"动态注入只在消息末尾"约束 |
| F | 工具描述审查 | 第二批候选 | 用 A 的工具选对率指标验收 |
| G | 经验写入验证门 + 过期整理 | 第二批候选 | 依赖 A 的轨迹验证结果 |
| H | v7.1/v8 收敛决策 | 延后单独讨论 | 需先积累 v8 白名单场景的评估数据（A 的产物） |

## 7. 风险与已知限制

- **裁判同源**：Rubric 裁判（qwen3-max）与被评系统 primary（qwen 系）同家族，
  用"确定性硬门 + LLM 仅评软维度"缓解；引入异源 API Key 后可升级
- **评估成本**：30 条端到端用例 × 本地 14b 推理耗时较长，故门禁日常仍用规则层快速评估，
  e2e 评估按里程碑/提交前运行
- **数据集规模**：30 条下成功率的标准误约 ±9pp，小幅 delta 不足以支持结论；
  配对口径 + bad case 持续回流逐步扩大样本
