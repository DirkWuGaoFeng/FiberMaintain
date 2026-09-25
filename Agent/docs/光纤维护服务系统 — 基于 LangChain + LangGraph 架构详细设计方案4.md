# 光纤维护服务 Agent 系统 — 工业级完整设计方案 v8.0-Optimized

**文档版本：** v8.0-Optimized（基于 v7.0-Final 深度优化）
**编制日期：** 2026-07-29
**文档性质：** 架构设计规格书 + 实现蓝图
**适用范围：** 光纤维护智能体系统的架构评审、开发实施、测试验收

------

## 目录

- [第一部分：背景与问题定义](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第一部分背景与问题定义)
- [第二部分：设计哲学与核心原则](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第二部分设计哲学与核心原则)
- [第三部分：系统架构总览](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第三部分系统架构总览)
- [第四部分：L0 规则引擎与 Fast Path（含可学习规则升级）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第四部分l0-规则引擎与-fast-path)
- [第五部分：参数防线设计](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第五部分参数防线设计)
- [第六部分：主图编排与 Controlled Loop（含 Narrator 校验回环）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第六部分主图编排与-controlled-loop)
- [第七部分：Tool 层设计（含缓存策略）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第七部分tool-层设计)
- [第八部分：RAG 知识引擎（bge-large-zh-v1.5 + Milvus）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第八部分rag-知识引擎)
- [第九部分：实时事件与主动诊断（含告警风暴聚合）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第九部分实时事件与主动诊断)
- [第十部分：降级与容错策略（三级 LLM 梯度）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十部分降级与容错策略)
- [第十一部分：安全设计（含输出侧检测）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十一部分安全设计)
- [第十二部分：可观测性与审计（含决策链路）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十二部分可观测性与审计)
- [第十三部分：部署方案（含灰度发布）](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十三部分部署方案)
- [第十四部分：开发路线图与复杂度预算](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十四部分开发路线图与复杂度预算)
- [第十五部分：验收标准](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十五部分验收标准)
- [第十六部分：持续优化与自进化机制](https://www.qianwen.com/chat/c76dfe8fcb15479cadf62c51614339eb#第十六部分持续优化与自进化机制)

------

## 第一部分：背景与问题定义

### 1.1 行业背景

光纤通信网络是现代信息基础设施的核心。随着"东数西算"、5G 承载网、FTTR（光纤到房间）等国家战略的推进，光纤网络的规模和复杂度呈指数级增长：

| 指标               | 2020 年      | 2026 年（预估） | 增长  |
| ------------------ | ------------ | --------------- | ----- |
| 全国光缆总长度     | 5,169 万公里 | ~7,500 万公里   | +45%  |
| 单省网管光纤数     | ~50 万条     | ~120 万条       | +140% |
| 日均告警量（省级） | ~2,000 条    | ~8,000 条       | +300% |
| 运维人员数量       | ~200 人/省   | ~180 人/省      | -10%  |

**核心矛盾：** 网络规模快速增长，运维人力持续缩减。传统"人盯告警、手动排查"的模式已不可持续。

### 1.2 现有系统痛点

当前光纤维护依赖 C++ 后端服务（以下简称"后端"），提供 REST API + WebSocket 接口。运维人员通过 Web 前端操作：

| 痛点     | 具体表现                                                     | 影响               |
| -------- | ------------------------------------------------------------ | ------------------ |
| 操作复杂 | 查一条光纤需要：登录→选网元→选单盘→选端口→查连纤→查性能→查告警→人工比对 | 单次排查 5-10 分钟 |
| 信息分散 | 拓扑、性能、告警、趋势分布在不同页面，无法关联分析           | 根因定位困难       |
| 被动响应 | 只有人主动查询才能获取信息，告警来了不知道影响范围           | 故障扩大           |
| 经验依赖 | "衰耗 8dB 正不正常"取决于老师傅经验，新人无法独立判断        | 人才断层           |
| 报告低效 | 巡检报告需手动汇总数据、截图、填表                           | 一份报告 2-4 小时  |

### 1.3 项目目标

构建一个光纤维护智能体（Agent），作为运维人员的"AI 助手"：

| 目标         | 量化指标                                         |
| ------------ | ------------------------------------------------ |
| 自然语言查询 | "查 FIB-0012 的衰耗" → 2 秒内返回结果            |
| 智能诊断     | "FIB-0012 为什么变红了" → 自动多步排查，给出根因 |
| 批量操作     | "查所有红色光纤" → 自动聚合统计                  |
| 主动预警     | CRITICAL 告警 → 5 秒内自动诊断并推送             |
| 报告生成     | "生成本周巡检报告" → 自动生成结构化报告          |
| 知识问答     | "什么是 OOP？" → 基于知识库回答                  |

### 1.4 技术约束

| 约束         | 说明                                            | 影响                       |
| ------------ | ----------------------------------------------- | -------------------------- |
| 数据不出网   | 电信行业等保三级，所有数据必须在内网处理        | 必须本地部署 LLM           |
| LLM 能力有限 | 使用 qwen2.5 系列（本地 Ollama），非 GPT-4 级别 | 不能让 LLM 做复杂推理/计算 |
| 后端不可修改 | C++ 后端已上线运行，Agent 只能作为"前端"调用    | 仅 REST + WebSocket        |
| 高可用要求   | 7×24 运维，Agent 不可用不能影响原有系统         | 必须有完整降级链           |
| 可审计       | 等保三级要求所有操作可追溯，日志保留 180 天     | 全链路审计                 |
| 响应时间     | 运维人员耐心阈值 ~3 秒                          | 必须有 Fast Path           |

### 1.5 后端接口概览

后端提供 REST API（:8080）+ WebSocket（:8081），核心接口：

| 域                  | 接口数 | 关键接口                                           |
| ------------------- | ------ | -------------------------------------------------- |
| 拓扑（Topology）    | 8      | 连纤查询、场景查询、批量查询                       |
| 性能（Performance） | 6      | 光功率、历史性能、批量性能                         |
| 告警（Alarm）       | 7      | 当前告警、批量告警、PullCall                       |
| 光纤状态（Fiber）   | 6      | 连纤性能，连纤衰耗，颜色查询、统计、趋势，批量查询 |
| 设备（Board/NE）    | 6      | 单盘查询、网元查询                                 |
| 合计                | ~33    | —                                                  |

关键参数类型（全部为强类型）：

| 参数       | 后端类型         | 示例                         | 约束              |
| ---------- | ---------------- | ---------------------------- | ----------------- |
| fiber_id   | int32            | 1001                         | 正整数            |
| board_id   | int32            | 5                            | 正整数            |
| port_id    | int32            | 3                            | 正整数            |
| fiber_ids  | repeated int32   | [1, 2, 999]                  | ≤200              |
| ports      | repeated PortRef | [{"board_id":5,"port_id":3}] | 告警≤50，性能≤200 |
| color      | enum             | RED / YELLOW                 | 仅枚举值          |
| start_time | string           | "2026-07-22T00:00:00"        | ISO 8601          |

### 1.6 通信协议分层

| 通信方向             | 协议          | 说明                              |
| -------------------- | ------------- | --------------------------------- |
| Agent → API Gateway  | REST（:8080） | JSON 格式，JWT 认证               |
| Agent ← WebSocket    | WS（:8081）   | 实时事件推送（alarm/color/stats） |
| API Gateway → 微服务 | gRPC          | 内部，Agent 不直接接触            |
| 微服务 → 微服务      | gRPC          | 内部                              |

**结论：** Agent 作为"前端"角色，仅通过 REST + WebSocket 访问后端，不涉及 gRPC。

------

## 第二部分：设计哲学与核心原则

### 2.1 核心命题

> **LLM 是系统的"认知接口层"，不是"决策层"。LLM 的唯一职责是翻译。**

具体展开：

| LLM 负责（翻译）          | LLM 不负责（判断/计算/决策）         |
| ------------------------- | ------------------------------------ |
| 用户自然语言 → 结构化意图 | 判断衰耗是否异常（规则引擎）         |
| 结构化数据 → 自然语言报告 | 计算统计指标（程序）                 |
| 模糊表达 → 精确参数       | 决定调用哪个 API（图结构）           |
| 知识检索 → 组织回答       | 决定是否需要补充数据（程序+LLM辅助） |

这个命题的工程意义：

- LLM 出错 → 翻译错误 → 被校验层拦截 → 追问用户（可控）
- LLM 不可用 → 翻译层失效 → 规则引擎兜底（降级但可用）
- LLM 幻觉 → 编造数据 → 但数据全部来自后端 API（不可能编造）

### 2.2 架构模式：Harness + Controlled Loop

```
┌─────────────────────── HARNESS（驾驭框架）───────────────────────┐
│                                                                   │
│   图结构（StateGraph）── 控制流约束                                │
│   Pydantic Schema ──── 输出格式约束                               │
│   Tool 白名单 ──────── 能力边界约束                                │
│   降级链 ──────────── 可用性约束                                   │
│   审计日志 ─────────── 合规约束                                    │
│   Token 预算 ───────── 资源约束                                    │
│   Narrator 校验 ───── 输出质量约束 [v8.0 新增]                     │
│                                                                   │
│   ┌──────────────── CONTROLLED LOOP ────────────────┐            │
│   │                                                  │            │
│   │   DataCollector ⇄ AnalysisExpert (ReAct ≤3)     │            │
│   │   ReportGen → ReportEval (Reflection ≤1)        │            │
│   │   Narrator → NarratorValidator [v8.0 新增]      │            │
│   │                                                  │            │
│   │   终止保障：                                      │            │
│   │   ① 轮次上限 (≤3)                                │            │
│   │   ② LLM 调用预算 (≤10)                           │            │
│   │   ③ 无进展检测 (action_signature)                │            │
│   │   ④ Tool 全失败熔断                              │            │
│   │   ⑤ 意图漂移检测 [v8.0 新增]                     │            │
│   │                                                  │            │
│   └──────────────────────────────────────────────────┘            │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

**一句话：缰绳在手，马可以走，但不能跑偏。**

### 2.3 十条设计原则

| #    | 原则           | 含义                                         | 工程体现                 |
| ---- | -------------- | -------------------------------------------- | ------------------------ |
| P1   | LLM 只做翻译   | 判断由规则引擎，计算由程序，LLM 仅做语言转换 | judgment/narrator 分离   |
| P2   | 确定性优先     | 能用规则解决的不用 LLM，能用程序的不用规则   | L0 规则引擎前置          |
| P3   | 单一数据出口   | 仅 data_collector 子图可调用后端 API         | Tool 绑定隔离            |
| P4   | 受控 Loop      | 允许回环但必须有五重终止保障                 | continue_loop 函数       |
| P5   | 参数不可信     | 用户输入经三层校验 + 两道断言才能到达后端    | Parameter Gate           |
| P6   | 梯度降级       | 三级 LLM 梯度 + 规则兜底 + 离线缓存          | L0-L4 降级链             |
| P7   | 事件驱动       | 既响应主动查询，也响应实时事件触发自动诊断   | WebSocket + Proactive    |
| P8   | 全链路可审计   | 每个请求从输入到输出完整记录，满足等保三级   | audit_trail + LangFuse   |
| P9   | **输出可校验** | LLM 输出必须经程序化校验，不合格则降级模板   | NarratorValidator [v8.0] |
| P10  | **系统可进化** | 规则引擎、知识库、缓存从运行数据中持续学习   | 反馈闭环 [v8.0]          |

### 2.4 响应时间 SLA 分级

| 路径          | 触发条件               | 目标延迟 | 实现手段                   |
| ------------- | ---------------------- | -------- | -------------------------- |
| Fast Path     | L0 规则命中 + 单条查询 | < 1s     | 规则引擎 + 直接 API + 模板 |
| Normal Path   | L0 未命中 + LLM 识别   | < 5s     | LLM 意图 + API + LLM 表述  |
| Heavy Path    | 批量 / 报告 / 复杂分析 | < 15s    | Send 并发 + 流式输出       |
| Degraded Path | LLM/后端不可用         | < 2s     | 规则兜底 + 缓存 + 模板     |

------

## 第三部分：系统架构总览

### 3.1 分层架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          接入层 (Access Layer)                            │
│                                                                         │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ LangServe  │  │ WebSocket    │  │ APScheduler  │  │ Callback     │ │
│  │ REST :8000 │  │ EventListener│  │ (定时巡检)    │  │ (PullCall)   │ │
│  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
└────────┼────────────────┼─────────────────┼─────────────────┼──────────┘
         │                │                 │                 │
         ▼                ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       编排层 (Orchestration Layer)                        │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                      Main StateGraph                               │ │
│  │                                                                   │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │ │
│  │  │InputGuard│→│RuleEngine│→│ParamGate │→│  IntentRouter    │ │ │
│  │  │(安全过滤) │  │(L0可学习) │  │(参数校验) │  │(条件路由)        │ │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┬─────────┘ │ │
│  │                                                      │           │ │
│  │  ┌───────────────────────────────────────────────────▼─────────┐ │ │
│  │  │                    SubGraph Zone                             │ │ │
│  │  │                                                             │ │ │
│  │  │  ┌─────────────────── Controlled Loop ──────────────────┐  │ │
│  │  │  │                                                      │  │ │
│  │  │  │  DataCollector ⇄ RuleJudgment → Narrator             │  │ │
│  │  │  │       → NarratorValidator [v8.0]                     │  │ │
│  │  │  │       (ReAct ≤3, 五重终止)                            │  │ │
│  │  │  │                                                      │  │ │
│  │  │  │  ReportGen → ReportEval (Reflection ≤1)              │  │ │
│  │  │  │                                                      │  │ │
│  │  │  └──────────────────────────────────────────────────────┘  │ │
│  │  │                                                             │ │ │
│  │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │ │ │
│  │  │  │BatchDisp.│  │Knowl.QA │  │Degradation│                 │ │ │
│  │  │  │(Send并发) │  │(RAG)    │  │(L1-L4)   │                 │ │ │
│  │  │  └──────────┘  └──────────┘  └──────────┘                 │ │ │
│  │  └─────────────────────────────────────────────────────────────┘ │ │
│  │                                                                   │ │
│  │  ┌─────────────────────────────────────────────────────────────┐ │ │
│  │  │              Proactive Diagnosis SubGraph                    │ │ │
│  │  │  EventTrigger → AlarmAggregator [v8.0] → QuickCollect       │ │ │
│  │  │  → AutoAnalyze → Alert/Report                               │ │ │
│  │  └─────────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        能力层 (Capability Layer)                          │
│                                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │Tool Layer│ │RAG Engine│ │Memory    │ │ParamNorm │ │Local Cache   │ │
│  │(23 Tools │ │(bge-large│ │(PG Check │ │(3-Layer  │ │(Redis +      │ │
│  │REST-only)│ │-zh+BM25) │ │pointer)  │ │+2 Assert)│ │SQLite L4)    │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      基础设施层 (Infrastructure Layer)                    │
│                                                                         │
│  ┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐│
│  │Ollama  │ │PostgreSQL│ │Redis   │ │Milvus  │ │LangFuse  │ │C++ 后端││
│  │(3-tier │ │(Checkpoint│ │(Event  │ │(Vector │ │+Prometheus│ │REST    ││
│  │LLM+Emb)│ │+ Audit)  │ │+Cache) │ │DB)     │ │+Grafana  │ │:8080   ││
│  └────────┘ └──────────┘ └────────┘ └────────┘ └──────────┘ └────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 技术选型

| 组件                 | 选型                             | 版本         | 理由                                               |
| -------------------- | -------------------------------- | ------------ | -------------------------------------------------- |
| **LLM（Primary）**   | **qwen2.5:14b**                  | Ollama 0.6+  | 意图识别 + 分析推理，中文能力最强                  |
| **LLM（Secondary）** | **qwen2.5:7b**                   | Ollama 0.6+  | 表述生成 + L1 降级备用                             |
| **LLM（Tertiary）**  | **qwen2.5:3b**                   | Ollama 0.6+  | L2 最终降级，极低资源占用                          |
| **Embedding**        | **bge-large-zh-v1.5**            | Ollama / TEI | **中文语义检索 SOTA，1024 维**                     |
| 编排框架             | LangGraph                        | ≥0.4         | 原生 StateGraph + Send + interrupt + Checkpointer  |
| LLM 框架             | LangChain                        | ≥0.3         | Tool/Prompt/Memory 生态                            |
| **向量库**           | **Milvus**                       | **≥2.4**     | **生产级向量数据库，支持十亿级向量，GPU 加速检索** |
| Checkpointer         | PostgreSQL                       | 16           | 并发支持，审计日志同库                             |
| 事件队列 + 缓存      | Redis Streams                    | 7            | WebSocket 事件缓冲 + Tool 结果缓存 + 发布订阅      |
| 本地缓存（L4）       | SQLite（aiosqlite）              | —            | 零依赖，L4 离线兜底                                |
| HTTP 客户端          | httpx.AsyncClient                | ≥0.27        | 连接池 + 异步 + 超时控制                           |
| 可观测               | LangFuse（主）+ Prometheus（辅） | —            | Trace + Metrics 双支柱                             |
| 定时任务             | APScheduler                      | ≥3.10        | 轻量，无需 Celery                                  |
| 部署                 | Docker Compose                   | —            | MVP 6 容器，生产 10 容器                           |

### 3.3 项目目录结构

```
fiber-agent/
├── src/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理（含三级 LLM 配置）
│   ├── graph/
│   │   ├── state.py               # State 定义
│   │   ├── main_graph.py          # 主图构建
│   │   ├── routing.py             # 条件路由函数
│   │   └── subgraphs/
│   │       ├── data_collector.py  # 数据采集子图
│   │       ├── batch_dispatcher.py# 批量分发（Send）
│   │       ├── knowledge_qa.py    # RAG 问答子图
│   │       └── proactive.py       # 主动诊断子图
│   ├── nodes/
│   │   ├── input_guard.py         # 安全过滤
│   │   ├── rule_engine.py         # L0 规则引擎（含可学习层）[v8.0 升级]
│   │   ├── param_gate.py          # 参数校验关卡
│   │   ├── intent_classifier.py   # LLM 意图识别（14b）
│   │   ├── rule_judgment.py       # 规则判断（程序化）
│   │   ├── narrator.py            # LLM 表述（7b，仅翻译）
│   │   ├── narrator_validator.py  # 表述校验（程序化）[v8.0 新增]
│   │   ├── report_generator.py    # 报告生成
│   │   ├── report_evaluator.py    # 报告评估（Reflection）
│   │   ├── clarification.py       # 追问（interrupt）
│   │   ├── context_compressor.py  # 上下文压缩 [v8.0 新增]
│   │   └── degradation.py         # 降级处理
│   ├── tools/
│   │   ├── _http_client.py        # HTTP 客户端（连接池+熔断）
│   │   ├── _cache_layer.py        # Tool 结果缓存层 [v8.0 新增]
│   │   ├── fiber_tools.py         # 光纤查询 Tool
│   │   ├── alarm_tools.py         # 告警查询 Tool
│   │   ├── performance_tools.py   # 性能查询 Tool
│   │   ├── topology_tools.py      # 拓扑查询 Tool
│   │   ├── stats_tools.py         # 统计/趋势 Tool
│   │   ├── event_tools.py         # 事件查询 Tool
│   │   └── pullcall_tools.py      # PullCall Tool
│   ├── rag/
│   │   ├── engine.py              # RAG 引擎（bge-large-zh + Milvus + BM25）
│   │   ├── ingest.py              # 文档入库（分层知识库）[v8.0 升级]
│   │   ├── query_rewriter.py      # Query 改写
│   │   ├── quality_monitor.py     # 检索质量监控 [v8.0 新增]
│   │   └── knowledge_base/        # 知识库文档（分层）
│   │       ├── L1_standards/      # 标准规范
│   │       ├── L2_manuals/        # 设备手册
│   │       ├── L3_sop/            # 运维 SOP
│   │       └── L4_cases/          # 历史案例
│   ├── events/
│   │   ├── listener.py            # WebSocket 监听器
│   │   ├── router.py              # 事件路由规则
│   │   └── alarm_aggregator.py    # 告警风暴聚合 [v8.0 新增]
│   ├── cache/
│   │   ├── redis_cache.py         # Redis Tool 缓存 [v8.0 新增]
│   │   ├── local_cache.py         # SQLite 本地缓存（L4）
│   │   └── intent_cache.py        # 意图 Embedding 缓存 [v8.0 新增]
│   ├── security/
│   │   ├── input_guard.py         # Prompt 注入检测（输入侧）
│   │   ├── output_sanitizer.py    # 输出侧净化 [v8.0 新增]
│   │   └── output_filter.py       # 敏感信息脱敏
│   ├── observability/
│   │   ├── metrics.py             # Prometheus 指标
│   │   ├── audit.py               # 审计日志（含决策链路）[v8.0 升级]
│   │   └── tracing.py             # LangFuse 集成
│   ├── resilience/
│   │   ├── circuit_breaker.py     # 熔断器
│   │   ├── degradation.py         # 降级管理器（三级 LLM）[v8.0 升级]
│   │   └── health_probe.py        # 健康探测
│   └── feedback/
│       ├── collector.py           # 用户反馈收集 [v8.0 新增]
│       └── rule_learner.py        # 规则自动学习 [v8.0 新增]
├── tests/
│   ├── golden_set/                # 50 条 Golden Set
│   ├── test_rule_engine.py
│   ├── test_param_gate.py
│   ├── test_loop.py
│   ├── test_narrator_validator.py # [v8.0 新增]
│   └── test_degradation.py
├── templates/
│   └── registry.yaml              # 模板注册表 [v8.0 新增]
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

------

## 第四部分：L0 规则引擎与 Fast Path

### 4.1 设计动机

基于电信运维工单统计，78% 的日常查询是模式化的：

| 模式         | 占比 | 示例                 |
| ------------ | ---- | -------------------- |
| 单条光纤查询 | 35%  | "查光纤1001的衰耗"   |
| 告警查询     | 20%  | "5号盘3口有什么告警" |
| 颜色查询     | 12%  | "现在有哪些红色光纤" |
| 统计查询     | 11%  | "光纤总数多少"       |
| 合计         | 78%  | —                    |

如果每次都走 LLM 意图识别（2-4s），系统响应时间不可接受。

### 4.2 三层可学习规则引擎 [v8.0 升级]

> **v8.0 核心升级：** 将静态正则规则升级为三层可学习架构，系统运行越久，Fast Path 命中率越高。

```
┌─────────────────────────────────────────────────────────┐
│              L0 规则引擎 v2（可学习架构）                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Layer 1: 硬规则（正则 + 关键词）                         │
│     ├── 25-30 条核心规则                                 │
│     ├── 优先级：精确匹配 > 前缀匹配 > 关键词匹配          │
│     └── 冲突仲裁：confidence 最高者胜出，平局走 Layer 2   │
│                                                         │
│  Layer 2: 软规则（Embedding 相似度缓存）[v8.0 新增]       │
│     ├── 将 LLM 识别过的 (query, intent, params) 三元组   │
│     │   存入 Redis（TTL 7天）                            │
│     ├── 新 query 先做 bge-large-zh cosine sim > 0.92    │
│     └── 命中 → 直接复用 intent+params（~5ms）            │
│                                                         │
│  Layer 3: LLM 意图识别（当前 Slow Path）                  │
│     └── Layer 1/2 均未命中时降级到此                     │
│                                                         │
│  反馈闭环：                                              │
│     LLM 识别结果 → 自动写入 Layer 2 缓存                 │
│     运维人员纠正 → 写入 Layer 1 硬规则（人工审核后）       │
└─────────────────────────────────────────────────────────┘
```

**预期收益：** 系统运行 1 个月后，Fast Path 命中率可从初始 78% 提升至 90%+，LLM 调用量持续下降。

### 4.3 规则引擎实现

```python
# src/nodes/rule_engine.py
import re
import json
from dataclasses import dataclass
from typing import Optional
from src.cache.intent_cache import IntentCache

@dataclass
class RuleMatch:
    """规则匹配结果"""
    intent: str
    params: dict
    confidence: float
    template_id: str
    fast_path_eligible: bool
    match_layer: str  # "hard_rule" / "embedding_cache" / "llm" [v8.0]

class RuleEngine:
    """
    L0 规则引擎 v2：三层可学习架构。
    - Layer 1: 正则 + 关键词（< 10ms）
    - Layer 2: Embedding 相似度缓存（< 5ms）[v8.0]
    - Layer 3: 未命中 → 交由 LLM
    """

    # ===== Layer 1: 硬规则定义（25-30 条）=====
    RULES = [
        {
            "id": "R001",
            "pattern": r'(?:查|看|查询|帮我看看)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:衰耗|spanloss|损耗|dB值)',
            "intent": "spanloss_query",
            "param_extract": lambda m: {"fiber_id": int(m.group(1))},
            "template": "T_SPANLOSS",
            "fast_path": True,
        },
        {
            "id": "R002",
            "pattern": r'(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:连纤|连接|拓扑)',
            "intent": "connection_query",
            "param_extract": lambda m: {"fiber_id": int(m.group(1))},
            "template": "T_CONNECTION",
            "fast_path": True,
        },
        {
            "id": "R003",
            "pattern": r'(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:性能|光功率|OOP|IOP)',
            "intent": "performance_query",
            "param_extract": lambda m: {"fiber_id": int(m.group(1))},
            "template": "T_PERFORMANCE",
            "fast_path": True,
        },
        {
            "id": "R004",
            "pattern": r'(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:告警|alarm)',
            "intent": "fiber_alarm_query",
            "param_extract": lambda m: {"fiber_id": int(m.group(1))},
            "template": "T_FIBER_ALARM",
            "fast_path": True,
        },
        {
            "id": "R010",
            "pattern": r'(\d+)\s*号?\s*(?:盘|单盘|板)\s*(\d+)\s*号?\s*(?:口|端口)\s*(?:的)?\s*(?:告警|alarm)',
            "intent": "port_alarm_query",
            "param_extract": lambda m: {"board_id": int(m.group(1)), "port_id": int(m.group(2))},
            "template": "T_PORT_ALARM",
            "fast_path": True,
        },
        {
            "id": "R020",
            "pattern": r'(?:有哪些|多少|查|看)\s*(红色|RED|red)\s*(?:光纤|的)',
            "intent": "colored_query",
            "param_extract": lambda m: {"color": "RED"},
            "template": "T_COLORED",
            "fast_path": True,
        },
        {
            "id": "R021",
            "pattern": r'(?:有哪些|多少|查|看)\s*(黄色|YELLOW|yellow)\s*(?:光纤|的)',
            "intent": "colored_query",
            "param_extract": lambda m: {"color": "YELLOW"},
            "template": "T_COLORED",
            "fast_path": True,
        },
        {
            "id": "R030",
            "pattern": r'(?:光纤|连纤)\s*(?:总数|总共|一共|有多少)',
            "intent": "stats_query",
            "param_extract": lambda m: {},
            "template": "T_STATS",
            "fast_path": True,
        },
        {
            "id": "R031",
            "pattern": r'(?:趋势|变化|统计)\s*(?:图|数据|报告)?',
            "intent": "trend_query",
            "param_extract": lambda m: {},
            "template": "T_TREND",
            "fast_path": True,
        },
        {
            "id": "R040",
            "pattern": r'(?:什么是|解释|定义|含义)\s*(.{2,20})',
            "intent": "knowledge_qa",
            "param_extract": lambda m: {"question": m.group(1)},
            "template": "T_KNOWLEDGE",
            "fast_path": False,
        },
    ]

    @classmethod
    async def match(cls, user_input: str) -> Optional[RuleMatch]:
        """
        三层匹配。命中返回 RuleMatch，未命中返回 None。
        """
        text = user_input.strip()

        # === Layer 1: 硬规则 ===
        for rule in cls.RULES:
            m = re.search(rule["pattern"], text, re.IGNORECASE)
            if m:
                try:
                    params = rule["param_extract"](m)
                    return RuleMatch(
                        intent=rule["intent"],
                        params=params,
                        confidence=1.0,
                        template_id=rule["template"],
                        fast_path_eligible=rule["fast_path"],
                        match_layer="hard_rule",
                    )
                except (ValueError, IndexError):
                    continue

        # === Layer 2: Embedding 相似度缓存 [v8.0] ===
        cached = await IntentCache.search_similar(text, threshold=0.92)
        if cached:
            return RuleMatch(
                intent=cached["intent"],
                params=cached["params"],
                confidence=cached["similarity"],
                template_id=cached.get("template_id", "T_GENERIC"),
                fast_path_eligible=cached.get("fast_path", False),
                match_layer="embedding_cache",
            )

        return None  # 未命中，交由 LLM
```

### 4.4 意图 Embedding 缓存 [v8.0 新增]

```python
# src/cache/intent_cache.py
import json
import numpy as np
from typing import Optional
import redis.asyncio as redis

class IntentCache:
    """
    Layer 2: 基于 bge-large-zh-v1.5 的意图相似度缓存。
    - LLM 识别结果自动写入（TTL 7天）
    - 新 query 做 cosine similarity > 0.92 匹配
    - 命中 → 直接复用 intent+params（~5ms）
    """
    REDIS_KEY = "intent_cache:vectors"
    TTL = 7 * 24 * 3600  # 7 天

    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis = redis.from_url(redis_url)

    async def store(self, query: str, embedding: list[float],
                    intent: str, params: dict, template_id: str,
                    fast_path: bool):
        """LLM 识别后自动写入"""
        entry = {
            "query": query,
            "embedding": json.dumps(embedding),
            "intent": intent,
            "params": json.dumps(params),
            "template_id": template_id,
            "fast_path": fast_path,
        }
        await self.redis.hset(
            self.REDIS_KEY,
            f"{query[:50]}_{intent}",
            json.dumps(entry),
        )
        await self.redis.expire(self.REDIS_KEY, self.TTL)

    async def search_similar(self, query: str,
                             threshold: float = 0.92) -> Optional[dict]:
        """
        在缓存中搜索相似意图。
        使用 bge-large-zh-v1.5 计算 query embedding，
        与缓存中的 embedding 做 cosine similarity。
        """
        from src.rag.engine import get_embeddings
        query_emb = await get_embeddings(query)

        all_entries = await self.redis.hgetall(self.REDIS_KEY)
        best_score = 0.0
        best_entry = None

        for _, raw in all_entries.items():
            entry = json.loads(raw)
            cached_emb = json.loads(entry["embedding"])
            sim = self._cosine_similarity(query_emb, cached_emb)
            if sim > best_score:
                best_score = sim
                best_entry = entry

        if best_score >= threshold and best_entry:
            return {
                "intent": best_entry["intent"],
                "params": json.loads(best_entry["params"]),
                "similarity": best_score,
                "template_id": best_entry["template_id"],
                "fast_path": best_entry["fast_path"],
            }
        return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
```

### 4.5 Fast Path 端到端流程

```
用户: "查光纤1001的衰耗"
         │
         ▼ (~0ms)
┌─ InputGuard ─────────────────────────────────────────┐
│  正则扫描 → 无注入 → PASS                             │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~5ms)
┌─ RuleEngine (Layer 1) ───────────────────────────────┐
│  命中 R001                                           │
│  intent = "spanloss_query"                           │
│  params = {"fiber_id": 1001}                         │
│  fast_path = True                                    │
│  match_layer = "hard_rule"                           │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~3ms)
┌─ ParamGate ──────────────────────────────────────────┐
│  fiber_id = 1001 → int ✅ → gt(0) ✅ → PASS          │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~5ms) [v8.0: 先查 Redis 缓存]
┌─ CacheLayer ─────────────────────────────────────────┐
│  Redis GET fiber:spanloss:1001                       │
│  HIT → 直接返回（跳过 API 调用）                       │
│  MISS → 继续调用后端 API                              │
└──────────────────────────────────────────────────────┘
         │ (MISS)
         ▼ (~150ms)
┌─ DirectAPI ──────────────────────────────────────────┐
│  GET /api/v1/fibers/1001/spanloss                    │
│  Response: {"fiber_id":1001, "spanloss":3.2, ...}   │
│  → 异步写入 Redis（TTL 30s）                          │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~2ms)
┌─ TemplateRenderer ───────────────────────────────────┐
│  模板 T_SPANLOSS:                                    │
│  "光纤 1001 当前衰耗为 3.2 dB（阈值 5 dB），状态正常。"│
│  + 判断: 3.2 < 5 → "✅ 正常"                         │
└──────────────────────────────────────────────────────┘
         │
         ▼
总耗时: ~160ms（缓存命中时 ~15ms）← Fast Path 目标 < 1s ✅
LLM 调用: 0 次
Token 消耗: 0
```

### 4.6 规则引擎维护机制

| 机制                | 说明                                                    |
| ------------------- | ------------------------------------------------------- |
| 配置化              | 规则存储在 YAML 文件中，非硬编码                        |
| 热更新              | 修改规则文件后无需重启，通过 API 触发重载               |
| 命中率监控          | Prometheus 指标 `rule_engine_hit_total{rule_id, layer}` |
| 未命中分析          | 每周统计 LLM 识别的高频意图，评估是否新增规则           |
| 回归测试            | 每次规则变更后跑 Golden Set（50 条），确保无退化        |
| **自动学习** [v8.0] | LLM 识别结果自动写入 Layer 2 缓存                       |
| **人工审核** [v8.0] | 运维人员纠正 → 审核后写入 Layer 1 硬规则                |

------

## 第五部分：参数防线设计

### 5.1 三层防线 + 两道断言

```
用户: "帮我查FIB-0012和13号光纤的衰耗，5号盘3口告警"
         │
         ▼
┌─ Layer 1: 提取（LLM 或规则引擎）─────────────────────────────────┐
│  输出: fiber_refs=["FIB-0012","13号光纤"], board_refs=["5号盘"],  │
│        port_refs=["3口"]                                         │
│  约束: Pydantic Schema（类型 + 描述）                             │
│  温度: 0.1（LLM 路径）/ 1.0（规则路径，确定性）                    │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Layer 2: 校验（Parameter Gate，程序化）─────────────────────────┐
│  ① 格式转换: "FIB-0012" → 12, "13号光纤" → 13, "5号盘" → 5      │
│  ② 业务规则: fiber_id > 0, len(fiber_ids) ≤ 200                 │
│  ③ 枚举校验: color ∈ {RED, YELLOW}                              │
│  ④ 时间校验: ISO 8601 格式                                      │
│  ⑤ 失败处理: 记录 parse_failures → 触发追问                      │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Layer 3: 执行（Tool 调用前的最后防线）──────────────────────────┐
│  assert isinstance(fiber_id, int) and fiber_id > 0              │
│  assert len(fiber_ids) <= 200                                   │
│  违反 → 抛出 AssertionError → 降级处理                           │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 后端兜底 ──────────────────────────────────────────────────────┐
│  若仍传入非法参数 → 后端返回 400 + error_code                    │
│  → 包装为 Tool 错误响应 → LLM 在 Loop 中自行修正                 │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Parameter Gate 实现

```python
# src/nodes/param_gate.py
import re
from datetime import datetime, timedelta
from typing import Optional, Literal
from pydantic import BaseModel, Field
from src.graph.state import NormalizedParams

class ParamGate:
    """
    参数校验关卡：将原始表达转换为后端接口要求的精确类型。
    纯程序化，零 LLM 调用，延迟 < 5ms。
    """
    _FIBER_PATTERNS = [
        (r'^FIB[-_]?(\d+)$', lambda m: int(m.group(1))),
        (r'^fiber[-_\s]?(\d+)$', lambda m: int(m.group(1))),
        (r'(\d+)\s*号?\s*光纤', lambda m: int(m.group(1))),
        (r'光纤\s*[#:]?\s*(\d+)', lambda m: int(m.group(1))),
        (r'^(\d+)$', lambda m: int(m.group(1))),
    ]
    _BOARD_PATTERNS = [
        (r'^board[-_\s]?(\d+)$', lambda m: int(m.group(1))),
        (r'(\d+)\s*号?\s*(?:盘|单盘|板)', lambda m: int(m.group(1))),
        (r'^(\d+)$', lambda m: int(m.group(1))),
    ]
    _PORT_PATTERNS = [
        (r'^port[-_\s]?(\d+)$', lambda m: int(m.group(1))),
        (r'(\d+)\s*号?\s*(?:口|端口)', lambda m: int(m.group(1))),
        (r'^(\d+)$', lambda m: int(m.group(1))),
    ]
    _COLOR_MAP = {
        "红色": "RED", "红": "RED", "red": "RED",
        "黄色": "YELLOW", "黄": "YELLOW", "yellow": "YELLOW",
        "绿色": "GREEN", "绿": "GREEN", "green": "GREEN",
    }

    @classmethod
    def validate_and_normalize(cls, raw: dict) -> NormalizedParams:
        failures = []
        fiber_ids = []
        for ref in raw.get("fiber_refs", []):
            fid = cls._extract_id(ref, cls._FIBER_PATTERNS)
            if fid is not None and fid > 0:
                fiber_ids.append(fid)
            else:
                failures.append(f"无法识别光纤标识: '{ref}'（示例: FIB-0012 或 12号光纤）")

        if len(fiber_ids) > 200:
            failures.append(f"批量上限 200 条，当前 {len(fiber_ids)} 条")
            fiber_ids = fiber_ids[:200]

        board_ids = []
        for ref in raw.get("board_refs", []):
            bid = cls._extract_id(ref, cls._BOARD_PATTERNS)
            if bid is not None and bid > 0:
                board_ids.append(bid)
            else:
                failures.append(f"无法识别单盘标识: '{ref}'（示例: 5号盘）")

        port_ids = []
        for ref in raw.get("port_refs", []):
            pid = cls._extract_id(ref, cls._PORT_PATTERNS)
            if pid is not None and pid > 0:
                port_ids.append(pid)
            else:
                failures.append(f"无法识别端口标识: '{ref}'（示例: 3口）")

        port_refs = []
        if board_ids and port_ids:
            if len(board_ids) == len(port_ids):
                port_refs = [{"board_id": b, "port_id": p}
                             for b, p in zip(board_ids, port_ids)]
            else:
                failures.append("单盘和端口数量不匹配")

        color = None
        color_ref = raw.get("color_ref")
        if color_ref:
            color = cls._COLOR_MAP.get(color_ref.strip().lower(),
                    cls._COLOR_MAP.get(color_ref.strip()))
            if color is None:
                failures.append(f"无法识别颜色: '{color_ref}'（仅支持: 红/黄/绿）")

        start_time, end_time = cls._parse_time(raw.get("time_expression", ""))

        return NormalizedParams(
            fiber_ids=fiber_ids, board_ids=board_ids,
            port_ids=port_ids, port_refs=port_refs,
            color=color, start_time=start_time, end_time=end_time,
            ne_id=raw.get("ne_id"), parse_failures=failures,
        )

    @classmethod
    def _extract_id(cls, text: str, patterns: list) -> Optional[int]:
        text = text.strip()
        for pattern, extractor in patterns:
            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return extractor(m)
                except (ValueError, IndexError):
                    continue
        return None

    @classmethod
    def _parse_time(cls, expr: str) -> tuple[Optional[str], Optional[str]]:
        if not expr:
            return (None, None)
        now = datetime.now()
        m = re.search(r'最近\s*(\d+)\s*(天|日|周|星期|月)', expr)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            delta = {'天': timedelta(days=n), '日': timedelta(days=n),
                     '周': timedelta(weeks=n), '星期': timedelta(weeks=n),
                     '月': timedelta(days=n*30)}[unit]
            return ((now - delta).strftime("%Y-%m-%dT00:00:00"),
                    now.strftime("%Y-%m-%dT%H:%M:%S"))
        m = re.search(r'(\d{1,2})月(\d{1,2})日?\s*(?:到|至|-|~)\s*(\d{1,2})日?', expr)
        if m:
            try:
                month, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
                start = datetime(now.year, month, d1)
                end = datetime(now.year, month, d2, 23, 59, 59)
                return (start.strftime("%Y-%m-%dT%H:%M:%S"),
                        end.strftime("%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                pass
        return (None, None)
```

### 5.3 追问机制（interrupt + Command）

```python
# src/nodes/clarification.py
from langgraph.types import interrupt, Command

async def clarification_node(state: MainGraphState) -> Command:
    """
    参数不完整时，使用 LangGraph 原生 interrupt() 暂停图执行。
    用户回复后，通过 Command(goto="rule_engine") 恢复。
    """
    params = state["normalized_params"]
    failures = params.parse_failures

    question_parts = ["抱歉，以下信息我没能正确识别：\n"]
    for f in failures:
        question_parts.append(f"  • {f}")
    question_parts.append("\n请补充说明，例如：")
    question_parts.append("  • 光纤编号：FIB-0012 或 12号光纤")
    question_parts.append("  • 单盘端口：5号盘3口")
    question_parts.append("  • 颜色：红色 / 黄色")
    question_parts.append("  • 时间：最近一周 / 7月22日到29日")

    user_reply = interrupt({
        "question": "\n".join(question_parts),
        "missing_params": failures,
    })

    return Command(
        goto="rule_engine",
        update={"user_input": user_reply}
    )
```

------

## 第六部分：主图编排与 Controlled Loop

### 6.1 State 定义

```python
# src/graph/state.py
from typing import TypedDict, Optional, Literal, Annotated
from pydantic import BaseModel, Field
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
import operator

class NormalizedParams(BaseModel):
    fiber_ids: list[int] = Field(default_factory=list)
    board_ids: list[int] = Field(default_factory=list)
    port_ids: list[int] = Field(default_factory=list)
    port_refs: list[dict] = Field(default_factory=list)
    color: Optional[Literal["RED", "YELLOW", "GREEN"]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    ne_id: Optional[int] = None
    parse_failures: list[str] = Field(default_factory=list)

class RuleJudgment(BaseModel):
    status: Literal["NORMAL", "WARNING", "CRITICAL"]
    findings: list[str]
    metrics: dict
    suggested_actions: list[str]

class AnalysisVerdict(BaseModel):
    conclusion: str
    severity: Literal["NORMAL", "WARNING", "CRITICAL"]
    evidence: list[str]
    confidence: float = Field(ge=0, le=1)
    need_more_data: bool = False
    additional_query: Optional[dict] = None

class LoopRecord(BaseModel):
    loop_number: int
    reason: str
    tool_requested: str
    action_signature: str
    timestamp: str

class MainGraphState(TypedDict):
    # 对话
    messages: Annotated[list[BaseMessage], add_messages]
    thread_id: str
    user_input: str
    # 规则引擎
    rule_match: Optional[dict]
    fast_path_result: Optional[str]
    # 意图与参数
    intent: Optional[str]
    raw_extractions: Optional[dict]
    normalized_params: Optional[NormalizedParams]
    # Loop 控制
    loop_count: int
    max_loops: int
    llm_call_count: int
    max_llm_calls: int
    no_progress_count: int
    last_action_signature: Optional[str]
    loop_history: Annotated[list[dict], operator.add]
    # 数据
    collected_data_summary: Optional[str]
    rule_judgment: Optional[RuleJudgment]
    analysis_verdict: Optional[AnalysisVerdict]
    # Narrator 校验 [v8.0]
    narration: Optional[str]
    narrator_validation_passed: Optional[bool]
    # 降级
    degradation_level: int
    # 审计
    request_id: str
    audit_trail: Annotated[list[dict], operator.add]
    # 元数据
    token_budget_remaining: int
    session_start_time: str
    processing_path: str
    # 意图漂移 [v8.0]
    intent_drift_detected: Optional[bool]
```

### 6.2 主图构建（含 Narrator 校验回环）[v8.0 升级]

```python
# src/graph/main_graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def build_main_graph():
    graph = StateGraph(MainGraphState)

    # ===== 节点注册 =====
    graph.add_node("input_guard", input_guard_node)
    graph.add_node("rule_engine", rule_engine_node)
    graph.add_node("fast_path_executor", fast_path_executor_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("param_gate", param_gate_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("data_collector", data_collector_subgraph)
    graph.add_node("rule_judgment", rule_judgment_node)
    graph.add_node("analysis_expert", analysis_expert_node)
    graph.add_node("narrator", narrator_node)
    graph.add_node("narrator_validator", narrator_validator_node)  # [v8.0]
    graph.add_node("template_fallback", template_fallback_node)    # [v8.0]
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("report_evaluator", report_evaluator_node)
    graph.add_node("batch_dispatcher", batch_dispatcher_node)
    graph.add_node("knowledge_qa", knowledge_qa_subgraph)
    graph.add_node("result_aggregator", result_aggregator_node)
    graph.add_node("degradation_handler", degradation_handler_node)
    graph.add_node("context_compressor", context_compressor_node)  # [v8.0]

    # ===== 边定义 =====
    graph.set_entry_point("input_guard")
    graph.add_edge("input_guard", "rule_engine")

    graph.add_conditional_edges(
        "rule_engine", route_after_rule_engine,
        {
            "fast_path": "fast_path_executor",
            "rule_hit_complex": "param_gate",
            "rule_miss": "intent_classifier",
        }
    )

    graph.add_edge("fast_path_executor", "result_aggregator")
    graph.add_edge("intent_classifier", "param_gate")

    graph.add_conditional_edges(
        "param_gate", route_after_param_gate,
        {"need_clarification": "clarification", "params_ok": "intent_router"}
    )

    graph.add_node("intent_router", intent_router_node)
    graph.add_conditional_edges(
        "intent_router", route_by_intent,
        {
            "data_query": "data_collector",
            "batch_query": "batch_dispatcher",
            "knowledge_qa": "knowledge_qa",
            "report": "data_collector",
            "chitchat": "result_aggregator",
        }
    )

    # ===== 核心：Controlled Loop =====
    graph.add_edge("data_collector", "rule_judgment")
    graph.add_edge("rule_judgment", "analysis_expert")

    graph.add_conditional_edges(
        "analysis_expert", route_after_analysis,
        {
            "need_more_data": "data_collector",
            "generate_report": "report_generator",
            "direct_narrate": "narrator",
            "degraded": "degradation_handler",
        }
    )

    # ===== Narrator → Validator → 校验回环 [v8.0] =====
    graph.add_edge("narrator", "narrator_validator")
    graph.add_conditional_edges(
        "narrator_validator", route_after_narrator_validation,
        {
            "pass": "result_aggregator",
            "fail": "template_fallback",  # 校验失败 → 模板兜底
        }
    )
    graph.add_edge("template_fallback", "result_aggregator")

    # ===== Reflection Loop =====
    graph.add_edge("report_generator", "report_evaluator")
    graph.add_conditional_edges(
        "report_evaluator", route_after_evaluation,
        {"pass": "result_aggregator", "refine": "report_generator"}
    )

    graph.add_edge("batch_dispatcher", "result_aggregator")
    graph.add_edge("knowledge_qa", "result_aggregator")
    graph.add_edge("degradation_handler", "result_aggregator")
    graph.add_edge("result_aggregator", END)

    checkpointer = AsyncPostgresSaver.from_conn_string(POSTGRES_URI)
    return graph.compile(checkpointer=checkpointer)
```

### 6.3 核心路由函数（五重终止保障）[v8.0 升级]

```python
# src/graph/routing.py
import hashlib

def route_after_analysis(state: MainGraphState) -> str:
    """
    ReAct Loop 核心路由 — 五重终止保障。
    ① 轮次上限: loop_count >= max_loops (3)
    ② LLM 预算: llm_call_count >= max_llm_calls (10)
    ③ 无进展: no_progress_count >= 2
    ④ Tool 全失败: 所有 API 返回错误
    ⑤ 意图漂移: 用户切换话题 [v8.0]
    """
    verdict = state.get("analysis_verdict")
    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)
    llm_calls = state.get("llm_call_count", 0)
    max_llm_calls = state.get("max_llm_calls", 10)
    no_progress = state.get("no_progress_count", 0)
    degradation = state.get("degradation_level", 0)

    if degradation >= 2:
        return "degraded"

    # ⑤ 意图漂移检测 [v8.0]
    if state.get("intent_drift_detected"):
        return _exit_loop(state, verdict)

    if loop_count >= max_loops:
        return _exit_loop(state, verdict)
    if llm_calls >= max_llm_calls:
        return _exit_loop(state, verdict)
    if no_progress >= 2:
        return _exit_loop(state, verdict)

    data_summary = state.get("collected_data_summary", "")
    if data_summary and all("错误" in line for line in data_summary.split("\n") if line.strip()):
        return "degraded"

    if verdict and verdict.need_more_data and verdict.additional_query:
        return "need_more_data"
    return _exit_loop(state, verdict)


def route_after_narrator_validation(state: MainGraphState) -> str:
    """[v8.0] Narrator 校验路由"""
    if state.get("narrator_validation_passed", True):
        return "pass"
    return "fail"


def _exit_loop(state: MainGraphState, verdict) -> str:
    intent = state.get("intent", "")
    if intent in ("spanloss_query", "connection_query", "performance_query",
                  "port_alarm_query", "colored_query", "stats_query"):
        return "direct_narrate"
    return "generate_report"

def compute_action_signature(action: str, observation: str) -> str:
    content = f"{action}|{observation[:500]}"
    return hashlib.md5(content.encode()).hexdigest()

def route_after_evaluation(state: MainGraphState) -> str:
    eval_result = state.get("_report_eval", {})
    refinement_count = eval_result.get("refinement_count", 0)
    if eval_result.get("passed", True):
        return "pass"
    if refinement_count >= 1:
        return "pass"
    return "refine"
```

### 6.4 判断/表述分离 + Narrator 校验回环 [v8.0 核心升级]

```python
# src/nodes/rule_judgment.py
from src.graph.state import MainGraphState, RuleJudgment

SPANLOSS_THRESHOLD = 5.0      # dB
OOP_RANGE = (-8.0, -2.0)     # dBm
IOP_RANGE = (-15.0, -8.0)    # dBm

async def rule_judgment_node(state: MainGraphState) -> dict:
    """程序化判断：根据阈值规则生成结构化结论。LLM 不参与。"""
    import re
    data_summary = state.get("collected_data_summary", "")
    findings = []
    metrics = {}
    status = "NORMAL"

    for line in data_summary.split("\n"):
        if "spanloss" in line.lower():
            m = re.search(r'spanloss[=:]\s*([\d.]+)', line)
            if m:
                spanloss = float(m.group(1))
                metrics["spanloss"] = spanloss
                if spanloss > SPANLOSS_THRESHOLD:
                    findings.append(
                        f"衰耗 {spanloss}dB 超过阈值 {SPANLOSS_THRESHOLD}dB"
                        f"（超出 {((spanloss - SPANLOSS_THRESHOLD) / SPANLOSS_THRESHOLD * 100):.0f}%）"
                    )
                    status = "CRITICAL" if spanloss > 8.0 else "WARNING"
                else:
                    findings.append(f"衰耗 {spanloss}dB，在阈值 {SPANLOSS_THRESHOLD}dB 内，正常")
        elif "告警" in line or "alarm" in line.lower():
            m = re.search(r'CRITICAL[=:]\s*(\d+)', line)
            if m and int(m.group(1)) > 0:
                findings.append(f"存在 {m.group(1)} 条 CRITICAL 告警")
                status = "CRITICAL"

    suggested_actions = []
    if status == "CRITICAL":
        suggested_actions.extend(["立即派单检修", "检查关联光纤是否受影响"])
    elif status == "WARNING":
        suggested_actions.extend(["列入下次巡检计划", "持续监控趋势变化"])

    judgment = RuleJudgment(
        status=status, findings=findings,
        metrics=metrics, suggested_actions=suggested_actions,
    )
    return {"rule_judgment": judgment}
# src/nodes/narrator.py
"""
叙述节点：LLM 仅做"翻译"。使用 qwen2.5:7b（Secondary）。
"""
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

narrator_llm = ChatOllama(model="qwen2.5:7b", temperature=0.3)

narrator_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是光纤维护报告的叙述员。
## 你的唯一职责
将以下【结构化判断】转换为通顺的自然语言回答。
## 硬约束（违反任何一条即为失败）
1. 不得修改任何数值（如 3.2dB 不能写成"约3dB"）
2. 不得添加判断中没有的结论
3. 不得编造数据
4. 不得改变严重程度判断（NORMAL/WARNING/CRITICAL）
5. 可以调整语序、增加连接词、使表述更自然
## 输出格式
直接用自然语言回答用户问题，200字以内。"""),
    ("human", """## 用户问题
{question}
## 结构化判断（不可修改）
状态: {status}
发现:
{findings}
关键指标: {metrics}
建议操作: {actions}
请将以上判断转换为自然语言回答。"""),
])

async def narrator_node(state: MainGraphState) -> dict:
    from langchain_core.messages import AIMessage
    judgment = state.get("rule_judgment")
    if not judgment:
        return {"messages": [AIMessage(content="暂无分析结果。")],
                "narration": "暂无分析结果。"}

    response = await (narrator_prompt | narrator_llm).ainvoke({
        "question": state["user_input"],
        "status": judgment.status,
        "findings": "\n".join(f"  • {f}" for f in judgment.findings),
        "metrics": str(judgment.metrics),
        "actions": "、".join(judgment.suggested_actions) or "无",
    })
    return {
        "messages": [AIMessage(content=response.content)],
        "narration": response.content,
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }
# src/nodes/narrator_validator.py  [v8.0 新增]
"""
Narrator 输出校验节点：程序化校验，零 LLM。
确保 LLM 表述未篡改规则判断的关键数据。
"""
import re
from src.graph.state import MainGraphState

COLOR_MAP = {1: "绿色", 2: "黄色", 3: "红色",
             "GREEN": "绿色", "YELLOW": "黄色", "RED": "红色"}

async def narrator_validator_node(state: MainGraphState) -> dict:
    """narrator 输出的程序化校验（零 LLM）"""
    judgment = state.get("rule_judgment")
    narration = state.get("narration", "")

    if not judgment or not narration:
        return {"narrator_validation_passed": True}

    errors = []

    # 校验 1：关键数值必须原样出现
    for key in ["spanloss", "threshold", "fiber_id"]:
        val = judgment.metrics.get(key)
        if val is not None and str(val) not in narration:
            errors.append(f"数值 {val} 在表述中缺失")

    # 校验 2：颜色词必须精确匹配
    for color_key, color_cn in COLOR_MAP.items():
        if str(color_key) in str(judgment.metrics.values()):
            if color_cn not in narration:
                errors.append(f"颜色表述不匹配：期望 {color_cn}")

    # 校验 3：禁止出现判断中不存在的告警类型
    alarm_types_in_judgment = set()
    for f in judgment.findings:
        for at in ["LOS", "LOF", "AIS", "RDI", "B1_EXC", "B2_EXC"]:
            if at in f:
                alarm_types_in_judgment.add(at)
    for at in ["LOS", "LOF", "AIS", "RDI", "B1_EXC", "B2_EXC"]:
        if at in narration and at not in alarm_types_in_judgment:
            errors.append(f"幻觉告警类型：{at}")

    # 校验 4：严重程度词一致性
    status_map = {"NORMAL": "正常", "WARNING": "警告", "CRITICAL": "严重"}
    expected_word = status_map.get(judgment.status, "")
    if judgment.status == "CRITICAL" and "正常" in narration and "不正常" not in narration:
        errors.append("严重程度表述矛盾：判断为 CRITICAL 但表述含'正常'")

    if errors:
        return {
            "narrator_validation_passed": False,
            "audit_trail": [{"event": "narrator_validation_failed", "errors": errors}],
        }

    return {"narrator_validation_passed": True}


async def template_fallback_node(state: MainGraphState) -> dict:
    """[v8.0] Narrator 校验失败时的模板兜底"""
    from langchain_core.messages import AIMessage
    judgment = state.get("rule_judgment")
    if not judgment:
        return {"messages": [AIMessage(content="分析结果暂不可用。")]}

    # 使用预定义模板生成回复
    lines = [f"📊 光纤状态：{judgment.status}"]
    for f in judgment.findings:
        lines.append(f"  • {f}")
    if judgment.suggested_actions:
        lines.append(f"💡 建议：{'；'.join(judgment.suggested_actions)}")
    lines.append("\n⚠️ （本回复由模板引擎生成，自然语言表述暂不可用）")

    return {"messages": [AIMessage(content="\n".join(lines))]}
```

### 6.5 上下文压缩机制 [v8.0 新增]

```python
# src/nodes/context_compressor.py
"""
每 5 轮触发一次上下文压缩，防止长对话 Token 溢出。
"""
from langchain_core.messages import SystemMessage

async def context_compressor_node(state: MainGraphState) -> dict:
    messages = state["messages"]
    if len(messages) <= 10:
        return {}

    recent = messages[-10:]
    history = messages[:-10]

    # 规则化摘要（零 LLM）
    summary_parts = []
    for msg in history:
        if hasattr(msg, 'content') and len(msg.content) > 0:
            summary_parts.append(msg.content[:80])
    summary = "；".join(summary_parts[-5:])  # 保留最近 5 条摘要

    compressed = [SystemMessage(content=f"[历史摘要] {summary}")] + recent
    return {"messages": compressed}
```

### 6.6 意图漂移检测 [v8.0 新增]

```python
# src/nodes/intent_drift_detector.py
def detect_intent_drift(state: MainGraphState) -> Optional[str]:
    """检测用户意图是否发生漂移（轻量级，非 LLM）"""
    current_intent = state.get("current_intent")
    new_message = state["messages"][-1].content if state["messages"] else ""

    switch_signals = ["换个问题", "另外", "还想问", "帮我生成", "导出", "算了"]
    if any(sig in new_message for sig in switch_signals):
        return "INTENT_SWITCH"

    if state.get("batch_progress") and not any(
        kw in new_message for kw in ["继续", "取消", "进度", "停止"]
    ):
        return "BATCH_INTERRUPT"

    return None
```

### 6.7 analysis_expert（Loop 推理环节，使用 qwen2.5:14b）

```python
# src/nodes/analysis_expert.py
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from src.graph.state import MainGraphState, AnalysisVerdict, LoopRecord
from src.graph.routing import compute_action_signature
from datetime import datetime

# Primary LLM: qwen2.5:14b 用于分析推理
analysis_llm = ChatOllama(
    model="qwen2.5:14b", temperature=0.1, seed=42,
).with_structured_output(AnalysisVerdict)

analysis_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是光纤维护分析专家。根据已有数据和规则判断，决定是否需要补充数据。
## 输出（严格 JSON）
- conclusion: 一句话结论
- severity: NORMAL / WARNING / CRITICAL
- evidence: 支撑数据点
- confidence: 0-1
- need_more_data: 是否需要补充（true/false）
- additional_query: {{"reason":"...", "tool":"...", "params":{{...}}}}
## 规则
1. 规则判断已给出明确结论且 confidence > 0.8 → need_more_data = false
2. 关键信息缺失 → need_more_data = true
3. 当前第 {loop_count} 轮（最多 {max_loops} 轮），谨慎使用补充机会
4. 每次补充必须有明确理由
5. 绝不编造数据"""),
    ("human", """## 用户问题
{question}
## 规则判断（程序化，可信）
{rule_judgment}
## 已收集数据摘要
{data_summary}
## 循环历史
{loop_history}
## 状态: 第 {loop_count}/{max_loops} 轮, LLM调用 {llm_calls}/{max_llm_calls}"""),
])

async def analysis_expert_node(state: MainGraphState) -> dict:
    loop_count = state.get("loop_count", 0)
    judgment = state.get("rule_judgment")

    judgment_text = "无" if not judgment else (
        f"状态: {judgment.status}\n"
        f"发现: {'; '.join(judgment.findings)}\n"
        f"指标: {judgment.metrics}"
    )

    history = state.get("loop_history", [])
    history_text = "无" if not history else "\n".join([
        f"  第{r['loop_number']}轮: {r['reason']}" for r in history
    ])

    verdict = await (analysis_prompt | analysis_llm).ainvoke({
        "question": state["user_input"],
        "rule_judgment": judgment_text,
        "data_summary": state.get("collected_data_summary", "暂无"),
        "loop_history": history_text,
        "loop_count": loop_count,
        "max_loops": state.get("max_loops", 3),
        "llm_calls": state.get("llm_call_count", 0),
        "max_llm_calls": state.get("max_llm_calls", 10),
    })

    updates = {
        "analysis_verdict": verdict,
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }

    if verdict.need_more_data and verdict.additional_query:
        action_sig = compute_action_signature(
            str(verdict.additional_query),
            state.get("collected_data_summary", "")[:500]
        )
        if action_sig == state.get("last_action_signature"):
            updates["no_progress_count"] = state.get("no_progress_count", 0) + 1
        else:
            updates["no_progress_count"] = 0
            updates["last_action_signature"] = action_sig

        record = LoopRecord(
            loop_number=loop_count + 1,
            reason=verdict.additional_query.get("reason", "未说明"),
            tool_requested=verdict.additional_query.get("tool", "unknown"),
            action_signature=action_sig,
            timestamp=datetime.now().isoformat(),
        )
        updates["loop_history"] = [record.model_dump()]
        updates["loop_count"] = loop_count + 1

    return updates
```

------

## 第七部分：Tool 层设计

### 7.1 Tool 清单（REST-only，与后端 v2.3 对齐）

| #    | Tool 名称                 | 后端 API                                | 方法   | 关键参数                       | 上限 |
| ---- | ------------------------- | --------------------------------------- | ------ | ------------------------------ | ---- |
| 1    | fiber_connection_query    | /api/v1/topology/fibers/{id}            | GET    | fiber_id: int                  | —    |
| 2    | fiber_scene_query         | /api/v1/topology/fibers/{id}/scene      | GET    | fiber_id: int                  | —    |
| 3    | fiber_performance_query   | /api/v1/fibers/{id}/performance         | GET    | fiber_id: int                  | —    |
| 4    | fiber_history_performance | /api/v1/fibers/{id}/performance/history | GET    | fiber_id: int, start/end: str  | —    |
| 5    | fiber_spanloss_query      | /api/v1/fibers/{id}/spanloss            | GET    | fiber_id: int                  | —    |
| 6    | batch_fiber_query         | /api/v1/topology/fibers/batch           | POST   | fiber_ids: list[int]           | ≤200 |
| 7    | alarm_query               | /api/v1/alarms/current                  | GET    | board_id: int, port_id: int    | —    |
| 8    | batch_alarm_query         | /api/v1/alarms/current/batch            | POST   | ports: list[PortRef]           | ≤50  |
| 9    | colored_fibers_query      | /api/v1/fibers/colored                  | GET    | color: Literal["RED","YELLOW"] | —    |
| 10   | fiber_stats_query         | /api/v1/fibers/stats                    | GET    | —                              | —    |
| 11   | fiber_trend_query         | /api/v1/fibers/stats/trend              | GET    | start/end: str (ISO8601)       | —    |
| 12   | board_query               | /api/v1/boards/{id}                     | GET    | board_id: int                  | —    |
| 13   | board_fibers_query        | /api/v1/boards/{id}/fibers              | GET    | board_id: int                  | —    |
| 14   | batch_board_query         | /api/v1/boards/batch                    | POST   | board_ids: list[int]           | ≤200 |
| 15   | batch_performance_query   | /api/v1/fibers/performance/batch        | POST   | ports: list[PortRef]           | ≤200 |
| 16   | ne_query                  | /api/v1/nes/{id}                        | GET    | ne_id: int                     | —    |
| 17   | pull_call_create          | /api/v1/alarms/pull-call                | POST   | ne_id: int                     | —    |
| 18   | pull_call_poll            | /api/v1/alarms/pull-call/{task_id}      | GET    | task_id: str                   | —    |
| 19   | pull_call_cancel          | /api/v1/alarms/pull-call/{task_id}      | DELETE | task_id: str                   | —    |
| 20   | event_query               | 内部 Redis                              | —      | channel: str, limit: int       | ≤50  |
| 21   | cache_query               | 内部 SQLite                             | —      | key: str                       | —    |
| 22   | audit_query               | 内部 PostgreSQL                         | —      | request_id: str                | —    |
| 23   | system_health             | 内部探测                                | —      | —                              | —    |

### 7.2 Tool 结果缓存策略 [v8.0 新增]

| Tool 类别                      | 缓存策略   | TTL  | 失效触发                       |
| ------------------------------ | ---------- | ---- | ------------------------------ |
| GetFiberStatus / GetFiberColor | Redis 缓存 | 30s  | FiberColorChanged 事件主动失效 |
| GetCurrentAlarms               | Redis 缓存 | 15s  | AlarmEvent 主动失效            |
| GetFiberAttenuation            | Redis 缓存 | 60s  | PerformanceData 事件主动失效   |
| GetTopology                    | Redis 缓存 | 300s | TopologyChanged 事件主动失效   |
| BatchGetFibers                 | **不缓存** | —    | 数据量大，缓存收益低           |
| 写操作（SetFiberColor 等）     | **不缓存** | —    | 强一致性要求                   |

**防穿透：** 对不存在的 fiber_id 缓存空结果（TTL 10s），避免重复查询后端。

```python
# src/tools/_cache_layer.py  [v8.0 新增]
import json
import redis.asyncio as redis

class ToolCacheLayer:
    """Tool 结果 Redis 缓存层"""

    CACHE_CONFIG = {
        "spanloss": {"ttl": 60, "prefix": "fiber:spanloss"},
        "alarm": {"ttl": 15, "prefix": "alarm:current"},
        "color": {"ttl": 30, "prefix": "fiber:color"},
        "topology": {"ttl": 300, "prefix": "topo:fiber"},
        "performance": {"ttl": 60, "prefix": "fiber:perf"},
    }

    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis = redis.from_url(redis_url)

    async def get_or_fetch(self, category: str, key: str,
                           fetch_fn, *args, **kwargs) -> str:
        config = self.CACHE_CONFIG.get(category)
        if not config:
            return await fetch_fn(*args, **kwargs)

        cache_key = f"{config['prefix']}:{key}"
        cached = await self.redis.get(cache_key)
        if cached:
            return cached.decode()

        result = await fetch_fn(*args, **kwargs)

        # 防穿透：空结果也缓存
        await self.redis.setex(cache_key, config["ttl"], result)
        return result

    async def invalidate(self, category: str, key: str):
        """事件驱动的主动失效"""
        config = self.CACHE_CONFIG.get(category)
        if config:
            await self.redis.delete(f"{config['prefix']}:{key}")
```

### 7.3 HTTP Client（连接池 + 熔断 + 错误转换）

```python
# src/tools/_http_client.py
import httpx
import json
import time
from typing import Optional

class FiberHttpClient:
    def __init__(self, base_url: str, max_connections: int = 20,
                 max_keepalive: int = 10, timeout_default: float = 3.0,
                 jwt_token: Optional[str] = None):
        self.base_url = base_url
        self.timeout_default = timeout_default
        self._client = httpx.AsyncClient(
            base_url=base_url,
            limits=httpx.Limits(max_connections=max_connections,
                                max_keepalive_connections=max_keepalive),
            timeout=httpx.Timeout(timeout_default),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {jwt_token}"} if jwt_token else {})},
        )
        self._failure_count = 0
        self._circuit_open_until = 0.0

    async def get(self, path: str, params: dict = None, timeout: float = None) -> str:
        return await self._request("GET", path, params=params, timeout=timeout)

    async def post(self, path: str, json_body: dict = None, timeout: float = None) -> str:
        return await self._request("POST", path, json=json_body, timeout=timeout)

    async def delete(self, path: str, timeout: float = None) -> str:
        return await self._request("DELETE", path, timeout=timeout)

    async def _request(self, method: str, path: str, **kwargs) -> str:
        if self._is_circuit_open():
            return json.dumps({
                "error": True, "error_code": "CIRCUIT_OPEN",
                "message": "后端服务暂时不可用（熔断中），请稍后重试"
            })
        try:
            if kwargs.get("timeout"):
                kwargs["timeout"] = httpx.Timeout(kwargs.pop("timeout"))
            resp = await self._client.request(method, path, **kwargs)
            if resp.status_code == 200:
                self._failure_count = 0
                await self._cache_response(path, resp.text)
                return resp.text
            if resp.status_code == 400:
                body = resp.json()
                return json.dumps({
                    "error": True,
                    "error_code": body.get("error_code", "INVALID_ARGUMENT"),
                    "message": f"参数校验失败: {body.get('message', '')}",
                    "hint": "请检查参数类型（ID应为正整数）和范围"
                })
            if resp.status_code == 404:
                return json.dumps({
                    "error": True, "error_code": "NOT_FOUND",
                    "message": f"资源不存在: {path}"
                })
            self._record_failure()
            return json.dumps({
                "error": True, "error_code": "SERVER_ERROR",
                "message": f"后端返回 {resp.status_code}"
            })
        except httpx.TimeoutException:
            self._record_failure()
            return json.dumps({
                "error": True, "error_code": "TIMEOUT",
                "message": f"请求超时 ({self.timeout_default}s): {path}"
            })
        except httpx.ConnectError:
            self._record_failure()
            return json.dumps({
                "error": True, "error_code": "CONNECT_FAILED",
                "message": "无法连接后端服务"
            })

    async def _cache_response(self, path: str, response_text: str):
        try:
            from src.cache.local_cache import LocalCache
            await LocalCache.set(path, response_text, ttl=300)
        except Exception:
            pass

    def _record_failure(self):
        self._failure_count += 1
        if self._failure_count >= 3:
            self._circuit_open_until = time.time() + 30

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until > time.time():
            return True
        if self._circuit_open_until > 0:
            self._circuit_open_until = 0
            self._failure_count = 0
        return False

    async def close(self):
        await self._client.aclose()
```

### 7.4 批量任务进度持久化 [v8.0 新增]

```python
# 批量任务进度持久化（Redis Hash）
async def batch_progress_tracker(task_id: str, result: dict, redis_client):
    """每个子任务完成后更新进度"""
    pipe = redis_client.pipeline()
    pipe.hincrby(f"batch:{task_id}", "completed", 1)
    pipe.hset(f"batch:{task_id}", f"result:{result.get('fiber_id')}", json.dumps(result))
    pipe.expire(f"batch:{task_id}", 3600)
    await pipe.execute()

    progress = int(await redis_client.hget(f"batch:{task_id}", "completed") or 0)
    total = int(await redis_client.hget(f"batch:{task_id}", "total") or 1)
    if progress % max(1, total // 10) == 0:
        await ws_manager.broadcast(f"批量任务 {task_id}: {progress}/{total}")
```

------

## 第八部分：RAG 知识引擎

### 8.1 架构（bge-large-zh-v1.5 + Milvus）[v8.0 全面升级]

```
用户: "什么是OOP？"
         │
         ▼
┌─ Query Rewriter（LLM 7b，可选）──────────────────────────────────┐
│  "什么是OOP" → "OOP 输出光功率 optical power 定义 含义 正常范围"   │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Hybrid Retriever ───────────────────────────────────────────────┐
│  ┌─────────────────────┐  ┌─────────────────┐                   │
│  │ Vector Search       │  │ BM25 Search     │                   │
│  │ (bge-large-zh-v1.5)│  │ (关键词匹配)     │                   │
│  │ Milvus HNSW        │  │                 │                   │
│  │ weight: 0.6        │  │ weight: 0.4     │                   │
│  │ k=5, thresh=0.55   │  │ k=5             │                   │
│  └────────┬────────────┘  └────────┬────────┘                   │
│           └──────────┬─────────────┘                            │
│                      ▼                                          │
│           EnsembleRetriever (RRF 融合)                           │
│           + 知识层级加权 [v8.0]                                   │
│           + 时间衰减（L4 层 >6月 × 0.7）[v8.0]                   │
│           Top-3 文档                                             │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ LLM 生成回答（qwen2.5:7b）──────────────────────────────────────┐
│  Context: [检索到的 3 段文档]                                     │
│  Prompt: "基于以下知识回答用户问题，不得编造..."                    │
│  输出: 自然语言回答 + 引用来源                                     │
└──────────────────────────────────────────────────────────────────┘
```

### 8.2 知识库分层 [v8.0 新增]

| 知识层级    | 内容                         | 更新频率 | 检索权重           | Milvus Partition |
| ----------- | ---------------------------- | -------- | ------------------ | ---------------- |
| L1 标准规范 | ITU-T G.652/G.655、YD/T 标准 | 年度     | 最高（不可覆盖）   | `standards`      |
| L2 设备手册 | 华为/中兴/烽火设备操作指南   | 季度     | 高                 | `manuals`        |
| L3 运维 SOP | 企业内部操作流程             | 月度     | 中                 | `sop`            |
| L4 历史案例 | 故障处理记录、经验总结       | 实时     | 参考（需标注时间） | `cases`          |

**时间衰减规则：** L4 层超过 6 个月的案例，相似度得分 × 0.7。

### 8.3 RAG 引擎配置

```python
# src/rag/engine.py
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_milvus import Milvus
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from pymilvus import connections, Collection

# ===== Embedding: bge-large-zh-v1.5 (1024维, 中文 SOTA) =====
embeddings = HuggingFaceEmbeddings(
    model_name="BAAI/bge-large-zh-v1.5",
    model_kwargs={"device": "cpu"},  # 生产环境可用 GPU
    encode_kwargs={"normalize_embeddings": True},  # 归一化，提升检索精度
)

# ===== 向量检索: Milvus =====
MILVUS_URI = "http://milvus:19530"
COLLECTION_NAME = "fiber_knowledge"

vectorstore = Milvus(
    embedding_function=embeddings,
    collection_name=COLLECTION_NAME,
    connection_args={"uri": MILVUS_URI},
    index_params={
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": {"M": 16, "efConstruction": 256},
    },
    search_params={"ef": 128},
)

vector_retriever = vectorstore.as_retriever(
    search_kwargs={"k": 5, "score_threshold": 0.55}
)

# ===== BM25 检索 =====
bm25_retriever = BM25Retriever.from_documents(all_documents, k=5)

# ===== 混合检索：Vector 权重更高（bge-large-zh 中文能力强）=====
hybrid_retriever = EnsembleRetriever(
    retrievers=[vector_retriever, bm25_retriever],
    weights=[0.6, 0.4],  # bge-large-zh 中文能力强，Vector 优先
)

# ===== 独立 Embedding 接口（供 IntentCache 使用）=====
async def get_embeddings(text: str) -> list[float]:
    return embeddings.embed_query(text)
```

### 8.4 检索质量监控 [v8.0 新增]

```python
# src/rag/quality_monitor.py
import numpy as np
from loguru import logger

class RAGQualityMonitor:
    """RAG 检索质量实时监控"""

    def __init__(self):
        self.recent_scores = []
        self.alert_threshold = 0.6
        self.alert_ratio = 0.2

    def record_retrieval(self, query: str, retrieved_docs: list, latency_ms: float):
        scores = [doc.metadata.get("score", 0) for doc in retrieved_docs[:5]]
        avg_score = np.mean(scores[:3]) if scores else 0

        self.recent_scores.append(avg_score)
        if len(self.recent_scores) > 100:
            self.recent_scores = self.recent_scores[-100:]

        # 告警：avg_score < 0.6 的比例 > 20%
        low_ratio = sum(1 for s in self.recent_scores if s < self.alert_threshold) / len(self.recent_scores)
        if low_ratio > self.alert_ratio:
            logger.warning(
                f"RAG 检索质量退化: {low_ratio:.0%} 的查询 avg_score < {self.alert_threshold}"
            )

        return {
            "query": query,
            "top_k_scores": scores,
            "avg_score": float(avg_score),
            "score_gap": scores[0] - scores[1] if len(scores) > 1 else 0,
            "retrieval_latency_ms": latency_ms,
        }
```

### 8.5 文档预处理

```python
# src/rag/ingest.py
TERM_ANNOTATIONS = {
    "衰耗": "spanloss/attenuation",
    "光功率": "optical power",
    "有源盘": "active board",
    "无源盘": "passive board",
    "告警": "alarm/alert",
    "连纤": "fiber connection",
    "网元": "network element (NE)",
    "色标": "color code",
    "阈值": "threshold",
    "OOP": "Output Optical Power 输出光功率",
    "IOP": "Input Optical Power 输入光功率",
}

def preprocess_for_ingest(text: str, layer: str = "L3") -> dict:
    """为中文文档追加英文关键词标注 + 层级元数据"""
    annotations = [f"{cn}({en})" for cn, en in TERM_ANNOTATIONS.items() if cn in text]
    if annotations:
        text += f"\n[关键词: {', '.join(annotations)}]"
    return {
        "text": text,
        "metadata": {
            "layer": layer,
            "ingest_time": datetime.now().isoformat(),
        }
    }
```

------

## 第九部分：实时事件与主动诊断

### 9.1 架构（含告警风暴聚合）[v8.0 升级]

```
C++ 后端 :8081 (WebSocket)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              EventListener Service（常驻协程）             │
│                                                         │
│  订阅: alarm / fiber_color / fiber_stats                 │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │         Alarm Aggregator [v8.0 新增]             │   │
│  │  30s 滑动窗口，同源告警合并为一次诊断              │   │
│  │  防止告警风暴导致 LLM 调用量暴增                   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Event Router（规则引擎）             │   │
│  │  IF alarm.level == CRITICAL (聚合后)             │   │
│  │    → 触发 Proactive Diagnosis                   │   │
│  │  IF color_change: GREEN → RED                   │   │
│  │    → 触发 Proactive Diagnosis                   │   │
│  │  IF stats_update                                │   │
│  │    → 写入 Redis + 更新本地缓存 + 失效 Tool 缓存  │   │
│  │  ELSE → 仅记录日志                              │   │
│  └─────────────────────────────────────────────────┘   │
│                      │                                  │
│                      ▼                                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Redis Streams                       │   │
│  │  events:alarm / events:color / events:stats     │   │
│  │  proactive:tasks（待诊断队列）                    │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼ (聚合后的 CRITICAL 事件)
┌─────────────────────────────────────────────────────────┐
│           Proactive Diagnosis SubGraph                   │
│  EventTrigger → QuickCollect → AutoAnalyze → Alert      │
│  超时 10s，结果推送到 WebSocket / 邮件 / 工单系统         │
└─────────────────────────────────────────────────────────┘
```

### 9.2 告警风暴聚合器 [v8.0 新增]

```python
# src/events/alarm_aggregator.py
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta
from loguru import logger

class AlarmAggregator:
    """
    告警风暴聚合：30s 滑动窗口内，同源（同网元/同光纤）告警合并为一次诊断。
    防止光缆中断等场景下 1 分钟 100+ CRITICAL 告警导致 LLM 调用量暴增。
    """
    WINDOW_SECONDS = 30
    MAX_BATCH_SIZE = 20

    def __init__(self):
        self._buffer: dict[str, list[dict]] = defaultdict(list)
        self._timers: dict[str, asyncio.Task] = {}

    async def add_alarm(self, payload: dict):
        source_key = self._get_source_key(payload)
        self._buffer[source_key].append(payload)

        if source_key not in self._timers:
            self._timers[source_key] = asyncio.create_task(
                self._flush_after_window(source_key)
            )

    def _get_source_key(self, payload: dict) -> str:
        ne_id = payload.get("ne_id", "unknown")
        fiber_id = payload.get("fiber_id", "unknown")
        return f"{ne_id}:{fiber_id}"

    async def _flush_after_window(self, source_key: str):
        await asyncio.sleep(self.WINDOW_SECONDS)
        alarms = self._buffer.pop(source_key, [])
        self._timers.pop(source_key, None)

        if not alarms:
            return

        aggregated = {
            "source_key": source_key,
            "alarm_count": len(alarms),
            "alarms": alarms[:self.MAX_BATCH_SIZE],
            "first_alarm_time": alarms[0].get("timestamp"),
            "last_alarm_time": alarms[-1].get("timestamp"),
            "max_level": max(a.get("level", "MINOR") for a in alarms),
            "aggregated_at": datetime.now().isoformat(),
        }

        logger.info(
            f"告警聚合: {source_key}, {len(alarms)} 条告警合并为 1 次诊断"
        )
        return aggregated
```

### 9.3 EventListener 实现

```python
# src/events/listener.py
import asyncio
import json
import websockets
import redis.asyncio as redis
from datetime import datetime
from loguru import logger
from src.events.alarm_aggregator import AlarmAggregator

class FiberEventListener:
    WS_URL = "ws://cpp-backend:8081/ws/v1/events"
    CHANNELS = ["alarm", "fiber_color", "fiber_stats"]

    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis = redis.from_url(redis_url)
        self.aggregator = AlarmAggregator()
        self._running = False

    async def start(self):
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    await ws.send(json.dumps({
                        "action": "subscribe", "channels": self.CHANNELS
                    }))
                    logger.info("WebSocket 已连接")
                    async for message in ws:
                        await self._handle(json.loads(message))
            except websockets.ConnectionClosed:
                logger.warning("WebSocket 断开，5s 后重连")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("EventListener 异常: {}", e)
                await asyncio.sleep(10)

    async def _handle(self, event: dict):
        channel = event.get("channel")
        payload = event.get("payload", {})

        await self.redis.xadd(
            f"events:{channel}",
            {"data": json.dumps(payload), "ts": datetime.now().isoformat()},
            maxlen=1000,
        )

        if channel == "alarm" and payload.get("type") == "ALARM_RAISED":
            if payload.get("level") in ("CRITICAL", "MAJOR"):
                # [v8.0] 通过聚合器而非直接触发
                aggregated = await self.aggregator.add_alarm(payload)
                if aggregated:
                    await self._trigger_proactive(aggregated)
        elif channel == "fiber_color" and payload.get("type") == "COLOR_CHANGED":
            if payload.get("old_color") == "GREEN" and payload.get("new_color") == "RED":
                await self._trigger_proactive(payload)
            # [v8.0] 主动失效 Tool 缓存
            from src.tools._cache_layer import ToolCacheLayer
            cache = ToolCacheLayer()
            await cache.invalidate("color", str(payload.get("fiber_id")))
        elif channel == "fiber_stats":
            from src.cache.local_cache import LocalCache
            await LocalCache.set("fiber_stats", json.dumps(payload), ttl=60)

    async def _trigger_proactive(self, payload: dict):
        task = {
            "trigger": "realtime_event",
            "event": payload,
            "priority": "HIGH",
            "created_at": datetime.now().isoformat(),
        }
        await self.redis.xadd("proactive:tasks", {"data": json.dumps(task)})
        logger.info("触发主动诊断: {}", payload.get("fiber_id", payload.get("source_key")))
```

------

## 第十部分：降级与容错策略

### 10.1 设计原则

> **保核心推理，砍非关键修饰。** 降级不是"每步都用规则替代"，而是"保住数据获取能力，简化分析表述"。

### 10.2 五级降级链（三级 LLM 梯度）[v8.0 升级]

| 级别 | 触发条件                       | LLM 模型                        | 策略                          | 用户感知                   | 响应时间 |
| ---- | ------------------------------ | ------------------------------- | ----------------------------- | -------------------------- | -------- |
| L0   | 正常                           | **14b**（推理）+ **7b**（表述） | 完整流程（规则+LLM+Loop）     | 无                         | < 5s     |
| L1   | 14b 响应 > 10s 或连续 2 次超时 | **7b**（推理+表述）             | 关闭 Loop，简化 Prompt        | 回答略简略                 | < 3s     |
| L2   | 7b 也不可用                    | **3b**（极简推理）              | 关闭 Reflection，极简 Prompt  | 质量下降                   | < 4s     |
| L3   | 所有模型不可用                 | 无                              | 保留 Tool 查询 + 规则模板输出 | "数据已查到，分析暂不可用" | < 2s     |
| L4   | 后端也不可用                   | 无                              | 本地缓存 + 纯 RAG + 明确告知  | "后端离线，提供缓存数据"   | < 1s     |

### 10.3 三级 LLM 配置 [v8.0 新增]

```python
# src/config.py
LLM_CONFIG = {
    "primary": {
        "model": "qwen2.5:14b",
        "temperature": 0.1,
        "use_cases": ["intent_classification", "analysis_expert", "report_generation"],
        "timeout": 15,
    },
    "secondary": {
        "model": "qwen2.5:7b",
        "temperature": 0.3,
        "use_cases": ["narrator", "knowledge_qa", "query_rewriter"],
        "timeout": 10,
    },
    "tertiary": {
        "model": "qwen2.5:3b",
        "temperature": 0.3,
        "use_cases": ["emergency_fallback"],
        "timeout": 8,
    },
}
```

### 10.4 降级管理器

```python
# src/resilience/degradation.py
import asyncio
import time
from enum import IntEnum
from loguru import logger

class DegradationLevel(IntEnum):
    NORMAL = 0
    L1_SIMPLIFIED = 1
    L2_SMALL_MODEL = 2
    L3_NO_LLM = 3
    L4_OFFLINE = 4

class DegradationManager:
    def __init__(self):
        self.level = DegradationLevel.NORMAL
        self._last_change = time.time()

    async def start_probing(self):
        while True:
            await asyncio.sleep(30)
            await self._probe()

    async def _probe(self):
        llm_14b_ok = await self._probe_model("qwen2.5:14b")
        llm_7b_ok = await self._probe_model("qwen2.5:7b")
        llm_3b_ok = await self._probe_model("qwen2.5:3b")
        backend_ok = await self._probe_backend()

        new_level = self._compute_level(llm_14b_ok, llm_7b_ok, llm_3b_ok, backend_ok)

        if new_level != self.level:
            old = self.level
            self.level = new_level
            self._last_change = time.time()
            logger.info(f"降级级别变更: {old.name} → {new_level.name}")
            await audit_log("degradation_change", {"from": old.name, "to": new_level.name})

    def _compute_level(self, ok_14b, ok_7b, ok_3b, backend_ok) -> DegradationLevel:
        if not backend_ok:
            return DegradationLevel.L4_OFFLINE
        if ok_14b:
            return DegradationLevel.NORMAL
        if ok_7b:
            return DegradationLevel.L1_SIMPLIFIED
        if ok_3b:
            return DegradationLevel.L2_SMALL_MODEL
        return DegradationLevel.L3_NO_LLM

    async def _probe_model(self, model: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post("http://ollama:11434/api/generate",
                    json={"model": model, "prompt": "hi", "stream": False})
                return r.status_code == 200
        except Exception:
            return False

    async def _probe_backend(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("http://cpp-backend:8080/api/v1/fibers/stats")
                return r.status_code == 200
        except Exception:
            return False
```

### 10.5 模板注册表 [v8.0 新增]

```yaml
# templates/registry.yaml
version: "1.0"
api_version: "v2.3"
templates:
  T_SPANLOSS:
    file: "templates/spanloss.j2"
    coverage: "fiber_spanloss_query"
    required_fields: ["fiber_id", "spanloss", "threshold"]
  T_CONNECTION:
    file: "templates/connection.j2"
    coverage: "fiber_connection_query"
    required_fields: ["fiber_id", "src_port", "dst_port"]
  T_PORT_ALARM:
    file: "templates/port_alarm.j2"
    coverage: "alarm_query"
    required_fields: ["board_id", "port_id", "alarms"]
  T_COLORED:
    file: "templates/colored.j2"
    coverage: "colored_fibers_query"
    required_fields: ["color", "count", "fibers"]
  T_STATS:
    file: "templates/stats.j2"
    coverage: "fiber_stats_query"
    required_fields: ["total", "red_count", "yellow_count", "green_count"]
  # ... 核心 10 个 Tool 100% 模板覆盖
```

### 10.6 本地缓存（L4 兜底）

```python
# src/cache/local_cache.py
import aiosqlite
import json
import time
from typing import Optional

class LocalCache:
    DB_PATH = "data/local_cache.db"

    @classmethod
    async def init(cls):
        async with aiosqlite.connect(cls.DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    ttl INTEGER NOT NULL DEFAULT 300
                )
            """)
            await db.commit()

    @classmethod
    async def set(cls, key: str, value: str, ttl: int = 300):
        async with aiosqlite.connect(cls.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO cache (key, value, updated_at, ttl) VALUES (?, ?, ?, ?)",
                (key, value, time.time(), ttl)
            )
            await db.commit()

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        async with aiosqlite.connect(cls.DB_PATH) as db:
            cursor = await db.execute(
                "SELECT value, updated_at, ttl FROM cache WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            value, updated_at, ttl = row
            if time.time() - updated_at > ttl:
                return None
            return value

    @classmethod
    async def get_with_staleness(cls, key: str) -> tuple[Optional[str], bool]:
        async with aiosqlite.connect(cls.DB_PATH) as db:
            cursor = await db.execute(
                "SELECT value, updated_at, ttl FROM cache WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None, False
            value, updated_at, ttl = row
            is_stale = (time.time() - updated_at) > ttl
            return value, is_stale
```

------

## 第十一部分：安全设计

### 11.1 五层安全架构 [v8.0 升级]

| 层                        | 措施                      | 实现                                  |
| ------------------------- | ------------------------- | ------------------------------------- |
| 输入层                    | Prompt 注入检测           | 正则 + 关键词黑名单                   |
| 认证层                    | JWT 透传                  | HTTP Client 注入 Authorization Header |
| 执行层                    | Tool 白名单 + 写操作确认  | 子图隔离 + interrupt()                |
| **输出层（净化）** [v8.0] | **Tool 返回结果注入检测** | **正则扫描 + 指令性文本过滤**         |
| 输出层（脱敏）            | 敏感信息脱敏              | IP/端口按角色脱敏                     |

### 11.2 Prompt 注入防护（输入侧）

```python
# src/security/input_guard.py
import re

INJECTION_PATTERNS = [
    r'忽略(以上|之前|所有)(指令|提示|规则|设定)',
    r'ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)',
    r'你(现在|从现在起)是(?!.*光纤)',
    r'act\s+as\s+(if|though)',
    r'pretend\s+(you|to\s+be)',
    r'(system|系统)\s*prompt',
    r'删除(所有|全部|一切)(光纤|数据|记录|配置)',
    r'DROP\s+TABLE',
    r'<script',
    r'<\|.*?\|>',  # 特殊 token [v8.0]
]

async def input_guard_node(state: MainGraphState) -> dict:
    user_input = state.get("user_input", "")
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, user_input, re.IGNORECASE):
            return {
                "messages": [AIMessage(
                    content="⚠️ 检测到异常输入，已拦截。如有正常需求请重新描述。"
                )],
                "processing_path": "blocked",
            }
    if len(user_input) > 2000:
        user_input = user_input[:2000]
    return {"user_input": user_input}
```

### 11.3 输出侧净化 [v8.0 新增]

```python
# src/security/output_sanitizer.py
import re

TOOL_OUTPUT_INJECTION_PATTERNS = [
    r"忽略以上.*指令",
    r"ignore (all )?(previous|above) instructions",
    r"你现在是.*模式",
    r"system prompt",
    r"<\|.*?\|>",
]

def sanitize_tool_output(tool_result: str) -> str:
    """Tool 返回结果的输出侧净化"""
    sanitized = tool_result
    for pattern in TOOL_OUTPUT_INJECTION_PATTERNS:
        sanitized = re.sub(pattern, "[已过滤]", sanitized, flags=re.IGNORECASE)
    return sanitized
```

### 11.4 写操作确认

```python
@tool
async def pull_call_create(ne_id: int) -> str:
    """创建 PullCall 任务（主动拉取告警）。⚠️ 此操作会触发设备上报。"""
    confirmed = interrupt({
        "question": f"确认对网元 {ne_id} 创建 PullCall 任务？此操作将触发设备主动上报告警。",
        "options": ["确认", "取消"],
    })
    if confirmed != "确认":
        return json.dumps({"cancelled": True, "message": "用户取消操作"})
    return await client.post("/api/v1/alarms/pull-call", json_body={"ne_id": ne_id})
```

------

## 第十二部分：可观测性与审计

### 12.1 三支柱

| 支柱    | 工具                 | 关注点                                       |
| ------- | -------------------- | -------------------------------------------- |
| Tracing | LangFuse             | 每次对话完整 Trace：意图→参数→Tool→Loop→输出 |
| Metrics | Prometheus + Grafana | P99 延迟、Loop 分布、降级率、Token 消耗      |
| Audit   | PostgreSQL（独立表） | 等保三级：身份、操作、结果、180 天保留       |

### 12.2 决策链路审计 [v8.0 升级]

```python
# src/observability/audit.py
async def write_audit_log(
    request_id: str, user_id: str, action: str,
    input_text: str, processing_path: str,
    api_calls: list[dict], output_text: str,
    token_used: int, latency_ms: float,
    degradation_level: int,
    decision_chain: dict = None,  # [v8.0] 决策链路
):
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO audit_logs (
                request_id, user_id, action, input_text,
                processing_path, api_calls, output_text,
                token_used, latency_ms, degradation_level,
                decision_chain, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        """,
            request_id, user_id, action, input_text,
            processing_path, json.dumps(api_calls), output_text,
            token_used, latency_ms, degradation_level,
            json.dumps(decision_chain or {}),
            datetime.now(),
        )
```

**决策链路结构示例 [v8.0]：**

```json
{
  "trace_id": "abc-123",
  "decision_chain": {
    "l0_rule_matched": "RULE_07_FIBER_ATTENUATION",
    "l0_match_layer": "hard_rule",
    "l0_confidence": 0.95,
    "path_taken": "FAST_PATH",
    "param_extraction": {"fiber_id": 1001, "source": "regex"},
    "param_validation": {"passed": true, "checks": ["int32_range", "non_null"]},
    "cache_hit": false,
    "tool_called": "GetFiberAttenuation",
    "tool_latency_ms": 45,
    "judgment_engine": "rule_based",
    "narrator_model": "qwen2.5:7b",
    "narrator_validation": {"passed": true},
    "total_latency_ms": 162
  },
  "security": {
    "injection_check": "passed",
    "output_sanitizer": "passed",
    "write_operation": false
  }
}
```

### 12.3 审计日志表结构

```sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL UNIQUE,
    user_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    input_text TEXT NOT NULL,
    processing_path VARCHAR(16) NOT NULL,
    api_calls JSONB,
    output_text TEXT,
    token_used INTEGER DEFAULT 0,
    latency_ms FLOAT NOT NULL,
    degradation_level SMALLINT DEFAULT 0,
    loop_count SMALLINT DEFAULT 0,
    decision_chain JSONB,          -- [v8.0] 决策链路
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_user ON audit_logs(user_id, created_at DESC);
CREATE INDEX idx_audit_time ON audit_logs(created_at DESC);
-- 自动清理（180天）通过 pg_cron
```

### 12.4 关键 Metrics

```python
# src/observability/metrics.py
from prometheus_client import Counter, Histogram, Gauge

request_total = Counter("agent_request_total", "请求总数", ["path", "intent"])
request_latency = Histogram("agent_request_latency_seconds", "请求延迟",
                           ["path"], buckets=[0.1, 0.5, 1, 2, 5, 10, 15, 30])
rule_hit_total = Counter("agent_rule_engine_hit_total", "规则命中", ["rule_id", "layer"])
rule_miss_total = Counter("agent_rule_engine_miss_total", "规则未命中")
tool_calls_total = Counter("agent_tool_calls_total", "Tool调用", ["tool", "status"])
tool_latency = Histogram("agent_tool_latency_seconds", "Tool延迟", ["tool"])
tool_cache_hits = Counter("agent_tool_cache_hits_total", "Tool缓存命中", ["category"])  # [v8.0]
loop_iterations = Histogram("agent_loop_iterations", "Loop次数", buckets=[0,1,2,3])
loop_no_progress = Counter("agent_loop_no_progress_total", "无进展终止")
degradation_level = Gauge("agent_degradation_level", "当前降级级别")
degradation_transitions = Counter("agent_degradation_transitions_total", "降级变更", ["from", "to"])
token_usage = Counter("agent_token_usage_total", "Token消耗", ["node", "model"])  # [v8.0] 按模型分
param_failures = Counter("agent_param_failures_total", "参数解析失败", ["type"])
narrator_validation_failures = Counter("agent_narrator_validation_failures_total", "Narrator校验失败")  # [v8.0]
rag_quality_scores = Histogram("agent_rag_quality_scores", "RAG检索质量", buckets=[0.3,0.5,0.6,0.7,0.8,0.9])  # [v8.0]
```

------

## 第十三部分：部署方案

### 13.1 MVP 阶段（6 容器）[v8.0 升级]

```yaml
# docker-compose.yml (MVP)
version: "3.9"
services:
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: [ollama_data:/root/.ollama]
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    # 启动后:
    # ollama pull qwen2.5:14b
    # ollama pull qwen2.5:7b
    # ollama pull qwen2.5:3b

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: fiber_agent
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    volumes: [pg_data:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru

  # [v8.0] Milvus 替代 ChromaDB
  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      ETCD_AUTO_COMPACTION_MODE: revision
      ETCD_AUTO_COMPACTION_RETENTION: "1000"
      ETCD_QUOTA_BACKEND_BYTES: "4294967296"
    volumes: [etcd_data:/etcd]

  milvus:
    image: milvusdb/milvus:v2.4-latest
    ports: ["19530:19530", "9091:9091"]
    depends_on: [etcd]
    environment:
      ETCD_ENDPOINTS: etcd:2379
    volumes: [milvus_data:/var/lib/milvus]

  agent:
    build: .
    ports: ["8000:8000"]
    depends_on: [ollama, postgres, redis, milvus]
    environment:
      OLLAMA_URL: http://ollama:11434
      POSTGRES_URI: postgresql+asyncpg://postgres:${PG_PASSWORD}@postgres/fiber_agent
      REDIS_URL: redis://redis:6379
      MILVUS_URI: http://milvus:19530
      BACKEND_URL: http://cpp-backend:8080
      WS_URL: ws://cpp-backend:8081/ws/v1/events
      LANGFUSE_PUBLIC_KEY: ${LANGFUSE_KEY}
      LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET}
      # [v8.0] 三级 LLM 配置
      LLM_PRIMARY: qwen2.5:14b
      LLM_SECONDARY: qwen2.5:7b
      LLM_TERTIARY: qwen2.5:3b
      EMBEDDING_MODEL: BAAI/bge-large-zh-v1.5
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./templates:/app/templates

volumes:
  ollama_data:
  pg_data:
  etcd_data:
  milvus_data:
```

### 13.2 生产阶段（+4 容器）

```yaml
  # 追加
  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3000:3000"]
    environment:
      DATABASE_URL: postgresql://postgres:${PG_PASSWORD}@postgres/langfuse
    depends_on: [postgres]

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:latest
    ports: ["3001:3000"]
    volumes:
      - ./monitoring/dashboards:/var/lib/grafana/dashboards
      - grafana_data:/var/lib/grafana

  # [v8.0] bge-large-zh Embedding 服务（可选独立部署）
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:1.5
    ports: ["8082:80"]
    volumes: [tei_data:/data]
    command: --model-id BAAI/bge-large-zh-v1.5
```

### 13.3 资源估算 [v8.0 更新]

| 组件              | CPU        | 内存       | 磁盘       | 备注                         |
| ----------------- | ---------- | ---------- | ---------- | ---------------------------- |
| Ollama (14b)      | 8 核       | 32 GB      | 15 GB      | **GPU 强烈推荐（A100 40G）** |
| Ollama (7b)       | 4 核       | 16 GB      | 10 GB      | 与 14b 共享进程              |
| Ollama (3b)       | 2 核       | 8 GB       | 5 GB       | 与 14b 共享进程              |
| bge-large-zh-v1.5 | 2 核       | 4 GB       | 2 GB       | TEI 或 Ollama 加载           |
| Agent             | 2 核       | 4 GB       | 1 GB       | Python 异步                  |
| PostgreSQL        | 1 核       | 2 GB       | 10 GB      | Checkpoint + Audit           |
| Redis             | 0.5 核     | 1 GB       | —          | 事件队列 + Tool 缓存         |
| Milvus            | 2 核       | 8 GB       | 10 GB      | 向量库（含 etcd）            |
| **合计**          | **~22 核** | **~75 GB** | **~53 GB** | **推荐 GPU 节点**            |

### 13.4 LLM 服务高可用 [v8.0 新增]

| 层级      | 模型                 | 部署位置                   | 用途                |
| --------- | -------------------- | -------------------------- | ------------------- |
| Primary   | qwen2.5:14b          | GPU 集群 A（2×A100）       | 意图识别 + 分析推理 |
| Secondary | qwen2.5:7b           | GPU 集群 B（1×A100）或 CPU | 表述生成 + L1 降级  |
| Tertiary  | qwen2.5:3b           | CPU（llama.cpp）           | L2 最终降级         |
| Emergency | 远程 API（通义千问） | 云端（需审批）             | 本地全挂时最后手段  |

### 13.5 灰度发布策略 [v8.0 新增]

```
┌──────────────────────────────────────────────┐
│              API Gateway                      │
│  流量分配：                                    │
│  - 90% → Agent v8.0-stable                   │
│  - 10% → Agent v8.1-canary                   │
│                                               │
│  灰度指标监控：                                │
│  - 意图识别准确率（对比 baseline）              │
│  - 平均响应时间                                │
│  - 用户满意度（thumbs up/down）                │
│  - LLM Token 消耗量                           │
│                                               │
│  自动回滚条件：                                │
│  - 准确率下降 > 5%                            │
│  - P99 延迟增加 > 50%                         │
│  - 错误率 > 2%                                │
└──────────────────────────────────────────────┘
```

------

## 第十四部分：开发路线图与复杂度预算

### 14.1 代码量预算 [v8.0 更新]

| 模块                                        | 代码量        | 占比     | 说明                           |
| ------------------------------------------- | ------------- | -------- | ------------------------------ |
| 规则引擎 (rule_engine.py + intent_cache.py) | ~1,100 行     | 13%      | 三层可学习规则                 |
| Tool 层 (23 个 Tool + cache_layer)          | ~1,400 行     | 17%      | 含 HTTP Client + Redis 缓存    |
| 参数关卡 (param_gate.py)                    | ~400 行       | 5%       | 正则 + 校验                    |
| 主图 + 路由                                 | ~700 行       | 9%       | StateGraph + 条件边 + 校验回环 |
| 子图 (data_collector 等)                    | ~800 行       | 10%      | 4 个子图                       |
| 节点 (analysis/narrator/validator/report)   | ~900 行       | 11%      | LLM 节点 + 校验                |
| RAG 引擎 (Milvus + bge + 分层)              | ~700 行       | 9%       | 检索 + 入库 + 质量监控         |
| 事件系统 (含告警聚合)                       | ~550 行       | 7%       | WebSocket + Redis + Aggregator |
| 降级 + 缓存 + 熔断                          | ~600 行       | 7%       | 三级 LLM + 容错层              |
| 安全 + 审计 + 可观测                        | ~550 行       | 7%       | 含输出侧净化 + 决策链路        |
| 反馈 + 自进化                               | ~300 行       | 4%       | 用户反馈 + 规则学习            |
| 配置 + 入口 + 工具                          | ~300 行       | 4%       | 胶水代码                       |
| **合计**                                    | **~8,300 行** | **100%** | —                              |

### 14.2 开发路线图（8 周）[v8.0 调整]

| 周次 | 目标                       | 交付物                                                       | 验收标准                                      |
| ---- | -------------------------- | ------------------------------------------------------------ | --------------------------------------------- |
| W1   | 骨架 + Fast Path           | 主图 + InputGuard + RuleEngine(L1) + ParamGate + 5 个核心 Tool + HTTP Client | "查光纤1001衰耗" Fast Path < 1s               |
| W2   | LLM 路径 + Loop            | IntentClassifier(14b) + DataCollector + RuleJudgment + AnalysisExpert(14b) + Narrator(7b) + 五重终止 | "FIB-0012为什么变红" 触发 2 轮 Loop           |
| W3   | Narrator 校验 + 上下文管理 | NarratorValidator + TemplateFallback + ContextCompressor + IntentDriftDetector | 校验失败 → 模板兜底；长对话不溢出             |
| W4   | 批量 + RAG + Milvus        | Send 并发 + bge-large-zh RAG + Milvus + 分层知识库 + PG Checkpointer | 批量 200 条 < 15s；RAG Recall@3 > 85%         |
| W5   | 事件 + 主动诊断 + 缓存     | WebSocket Listener + AlarmAggregator + Redis Tool 缓存 + Proactive SubGraph + L4 降级 | CRITICAL 告警 → 5s 内自动诊断；告警风暴不雪崩 |
| W6   | 安全 + 审计 + 报告         | 输出侧净化 + 决策链路审计 + Reflection Loop + 报告模板 + 三级 LLM 降级 | 安全测试通过；审计可查询                      |
| W7   | 可学习规则 + 反馈闭环      | IntentCache(L2) + RuleLearner + FeedbackCollector + RAG QualityMonitor | Fast Path 命中率可度量；反馈可收集            |
| W8   | 联调 + 压测 + 灰度 + 验收  | 端到端联调 + Golden Set 回归 + 并发压测 + 灰度发布 + 文档    | 5 类核心场景全部通过                          |

### 14.3 风险与缓解 [v8.0 更新]

| 风险                      | 概率 | 影响 | 缓解                                                |
| ------------------------- | ---- | ---- | --------------------------------------------------- |
| 14b 模型推理延迟过高      | 中   | 高   | GPU 加速；L1 降级切 7b；Fast Path 覆盖 78%+         |
| bge-large-zh 部署资源不足 | 低   | 中   | 支持 CPU 推理（延迟 ~50ms/query）；TEI 独立服务     |
| Milvus 运维复杂度         | 中   | 中   | MVP 用 Milvus Lite（嵌入式）；生产用 Milvus Cluster |
| 后端接口变更              | 低   | 高   | Tool 层抽象隔离；接口版本化                         |
| Loop 死循环               | 低   | 中   | 五重终止保障 + 无进展检测                           |
| 告警风暴                  | 中   | 高   | AlarmAggregator 30s 窗口聚合                        |
| 并发性能不足              | 中   | 中   | 连接池 + Send 并发 + Redis 缓存 + 批量 API          |

------

## 第十五部分：验收标准

### 15.1 功能验收（Golden Set，50 条）

| 类别      | 数量 | 示例                   | 通过标准           |
| --------- | ---- | ---------------------- | ------------------ |
| 单条查询  | 15   | "查光纤1001的衰耗"     | 正确返回数据，< 1s |
| 批量查询  | 8    | "查所有红色光纤"       | 正确聚合，< 10s    |
| 智能诊断  | 10   | "FIB-0012为什么变红"   | 多步排查，给出根因 |
| 知识问答  | 7    | "什么是OOP"            | 基于知识库，无幻觉 |
| 报告生成  | 5    | "生成本周巡检报告"     | 结构完整，数据准确 |
| 边界/异常 | 5    | "查光纤ABC" / 注入攻击 | 优雅追问/拦截      |

### 15.2 性能验收

| 指标            | 目标                    | 测试方法             |
| --------------- | ----------------------- | -------------------- |
| Fast Path P99   | < 1s（缓存命中 < 50ms） | 100 次规则命中请求   |
| Normal Path P99 | < 5s                    | 100 次 LLM 路径请求  |
| Heavy Path P99  | < 15s                   | 50 次批量 200 条请求 |
| 并发吞吐        | ≥ 10 QPS                | locust 压测          |
| 主动诊断延迟    | < 5s                    | 模拟 CRITICAL 事件   |
| RAG 检索延迟    | < 200ms                 | 100 次知识问答       |

### 15.3 可靠性验收

| 指标            | 目标                        | 测试方法            |
| --------------- | --------------------------- | ------------------- |
| 14b 不可用降级  | 30s 内切换 7b（L1）         | 停止 14b 模型       |
| 7b 不可用降级   | 30s 内切换 3b（L2）         | 停止 7b 模型        |
| 所有 LLM 不可用 | 30s 内切换 L3               | 停止 Ollama 容器    |
| 后端不可用降级  | 30s 内切换 L4               | 断开后端网络        |
| Loop 终止       | 100% 在 3 轮内终止          | 构造死循环场景      |
| 服务重启恢复    | 对话不丢失                  | 杀 agent 进程后重启 |
| 熔断恢复        | 30s 后自动探测              | 模拟后端 500        |
| 告警风暴        | 100 条 CRITICAL → ≤5 次诊断 | 模拟光缆中断        |

### 15.4 安全验收

| 测试项                        | 通过标准           |
| ----------------------------- | ------------------ |
| Prompt 注入（20 条攻击样本）  | 100% 拦截          |
| Tool 输出注入（10 条） [v8.0] | 100% 过滤          |
| 未认证访问                    | 返回 401           |
| 越权操作（写操作无确认）      | 被 interrupt 拦截  |
| 审计日志完整性（含决策链路）  | 所有请求可追溯     |
| 敏感信息脱敏                  | 输出无明文 IP/密码 |
| Narrator 校验 [v8.0]          | 数值篡改 100% 拦截 |

------

## 第十六部分：持续优化与自进化机制 [v8.0 新增]

### 16.1 用户反馈闭环

```python
# src/feedback/collector.py
class FeedbackCollector:
    """收集用户对 Agent 回复的反馈"""

    async def record_feedback(self, request_id: str, user_id: str,
                              rating: str, comment: str = ""):
        """rating: 'thumbs_up' / 'thumbs_down'"""
        await pg_pool.execute("""
            INSERT INTO user_feedback (request_id, user_id, rating, comment, created_at)
            VALUES ($1, $2, $3, $4, NOW())
        """, request_id, user_id, rating, comment)

        if rating == "thumbs_down":
            # 负反馈自动进入人工审核队列
            await redis_client.lpush("feedback:review_queue", json.dumps({
                "request_id": request_id,
                "user_id": user_id,
                "comment": comment,
            }))
```

### 16.2 规则自动学习

```python
# src/feedback/rule_learner.py
class RuleLearner:
    """从 LLM 识别的高频意图中自动提取规则模式"""

    async def weekly_analysis(self):
        """每周分析 LLM 识别的高频意图，建议新增硬规则"""
        rows = await pg_pool.fetch("""
            SELECT intent, COUNT(*) as cnt,
                   array_agg(DISTINCT input_text) as samples
            FROM audit_logs
            WHERE processing_path = 'normal'
              AND created_at > NOW() - INTERVAL '7 days'
            GROUP BY intent
            HAVING COUNT(*) > 20
            ORDER BY cnt DESC
        """)
        suggestions = []
        for row in rows:
            suggestions.append({
                "intent": row["intent"],
                "frequency": row["cnt"],
                "sample_queries": row["samples"][:5],
                "suggestion": "建议新增硬规则覆盖此高频意图",
            })
        return suggestions
```

### 16.3 RAG 知识库更新流程

| 触发条件       | 操作                                    | 负责人      |
| -------------- | --------------------------------------- | ----------- |
| 新设备型号接入 | 导入设备手册 → L2 层 → 重建 Milvus 索引 | 运维 + 开发 |
| 新 SOP 发布    | 导入 SOP 文档 → L3 层                   | 运维        |
| 故障处理完成   | 自动提取案例 → L4 层（标注时间）        | 系统自动    |
| RAG 质量告警   | 检查知识库覆盖率 → 补充文档             | 开发        |

------

## 附录 A：与历史版本对比

| 维度      | v5.0         | v6.0         | v7.0-Final                | **v8.0-Optimized（本文）**                  |
| --------- | ------------ | ------------ | ------------------------- | ------------------------------------------- |
| 架构模式  | Chain        | Agent + Loop | Harness + Controlled Loop | Harness + Controlled Loop + **校验回环**    |
| LLM 定位  | "做语言"     | "只做翻译"   | "只做翻译"                | "只做翻译" + **输出校验**                   |
| LLM 模型  | 7b           | 7b           | 7b                        | **14b / 7b / 3b 三级梯度**                  |
| Embedding | bge-large-zh | nomic-embed  | nomic-embed               | **bge-large-zh-v1.5**                       |
| 向量库    | —            | ChromaDB     | ChromaDB                  | **Milvus**                                  |
| 响应性能  | 无约束       | SLA 分级     | SLA + L0 规则             | SLA + L0 **可学习**规则                     |
| Loop 终止 | 三重         | 三重         | 四重                      | **五重**（+意图漂移）                       |
| 参数校验  | 四层         | 三层         | 三层+两断言               | 三层+两断言                                 |
| 降级      | 无           | 四级         | 五级                      | 五级（**三级 LLM 梯度**）                   |
| 安全      | 基础         | 基础         | 等保三级                  | 等保三级 + **输出侧净化**                   |
| 审计      | LangFuse     | 等保三级     | PG + LangFuse             | PG + LangFuse + **决策链路**                |
| 事件系统  | 无           | WebSocket    | WebSocket + Redis         | WebSocket + Redis + **告警聚合**            |
| RAG       | bge          | nomic+BM25   | nomic+BM25                | **bge-large-zh + Milvus + 分层 + 质量监控** |
| 自进化    | 无           | 无           | 无                        | **反馈闭环 + 规则学习 + RAG 监控**          |
| 代码量    | 未估算       | ~5800 行     | ~6600 行                  | **~8300 行**                                |
| 开发周期  | 4 周         | 5 周         | 6 周                      | **8 周**                                    |

## 附录 B：关键设计决策记录（ADR）

| #       | 决策                                       | 理由                                                | 替代方案         | 否决原因                  |
| ------- | ------------------------------------------ | --------------------------------------------------- | ---------------- | ------------------------- |
| ADR-001 | REST-only，不用 gRPC                       | Agent 是"前端"角色                                  | 增加 gRPC 适配   | 协议分层明确              |
| ADR-002 | **bge-large-zh-v1.5** [v8.0 变更]          | 中文语义检索 SOTA，1024 维，Recall@3 > 90%          | nomic-embed-text | 中文检索质量不足          |
| ADR-003 | **Vector 权重 0.6 > BM25 0.4** [v8.0 变更] | bge-large-zh 中文能力强，Vector 可主导              | BM25 0.6         | bge 已解决中文弱点        |
| ADR-004 | PostgreSQL 做 Checkpointer                 | 并发 + 审计同库                                     | SQLite           | 不支持并发写              |
| ADR-005 | 判断/表述分离                              | LLM 不可信做判断                                    | LLM 端到端       | 幻觉风险                  |
| ADR-006 | L0 规则引擎前置                            | 78% 请求无需 LLM                                    | 全部走 LLM       | 响应时间不可接受          |
| ADR-007 | Loop 最多 3 轮                             | 工业 SLA 约束                                       | 无限 Loop        | 无法承诺响应时间          |
| ADR-008 | interrupt() 追问                           | State 持久化                                        | 返回 END         | 上下文丢失                |
| ADR-009 | 本地 SQLite 缓存                           | L4 离线兜底                                         | 无缓存           | 网络分区不可用            |
| ADR-010 | 审计日志 180 天                            | 等保三级                                            | 7 天             | 不合规                    |
| ADR-011 | **Milvus 替代 ChromaDB** [v8.0]            | 生产级向量库，HNSW 索引，GPU 加速，十亿级扩展       | ChromaDB         | 单机瓶颈，无分布式        |
| ADR-012 | **三级 LLM 梯度** [v8.0]                   | 14b 推理 + 7b 表述 + 3b 兜底，资源与质量平衡        | 单 7b            | 推理能力不足 / 降级无梯度 |
| ADR-013 | **Narrator 校验回环** [v8.0]               | 程序化校验 LLM 输出，消除最后 1% 幻觉               | 信任 LLM         | 工业级不可接受            |
| ADR-014 | **告警风暴聚合** [v8.0]                    | 30s 窗口合并同源告警，防 LLM 调用雪崩               | 逐条触发         | 光缆中断时 100+ 告警      |
| ADR-015 | **可学习规则引擎** [v8.0]                  | Embedding 缓存 + 反馈闭环，Fast Path 命中率持续提升 | 静态规则         | 规则膨胀，维护成本高      |

## 附录 C：术语表

| 术语                         | 含义                                                   |
| ---------------------------- | ------------------------------------------------------ |
| Harness                      | 包裹 LLM 的工程化控制结构（图结构+Schema+降级+审计）   |
| Controlled Loop              | 在 Harness 约束内的有限回环（ReAct ≤3, Reflection ≤1） |
| Fast Path                    | 规则引擎命中后的极速响应路径（< 1s，零 LLM）           |
| Parameter Gate               | 参数校验关卡（格式转换+业务规则+枚举校验）             |
| Rule Judgment                | 程序化判断（基于阈值规则，非 LLM）                     |
| Narrator                     | LLM 叙述节点（仅翻译，不判断）                         |
| **NarratorValidator** [v8.0] | Narrator 输出的程序化校验节点                          |
| ReAct                        | Reason-Act-Observe 循环                                |
| Reflection                   | 生成-评估-修正 循环                                    |
| action_signature             | action+observation 的哈希，用于无进展检测              |
| PortRef                      | {board_id, port_id} 对象                               |
| PullCall                     | 主动拉取告警机制                                       |
| 等保三级                     | 信息安全等级保护第三级                                 |
| **AlarmAggregator** [v8.0]   | 告警风暴聚合器（30s 滑动窗口）                         |
| **IntentCache** [v8.0]       | 基于 Embedding 的意图相似度缓存（Layer 2）             |
| **ToolCacheLayer** [v8.0]    | Tool 结果 Redis 缓存层                                 |

------

> **文档结束**
>
> 本方案的核心信念：在通信运维领域，**"可靠"比"聪明"重要一万倍**。一个每次都能在 1 秒内给出正确答案的系统，远胜于一个偶尔惊艳但经常犯错的系统。LLM 是锦上添花，不是雪中送炭。规则引擎、参数校验、降级链、审计日志、输出校验——这些"无聊"的工程工作，才是工业级 Agent 的真正护城河。
>
> **v8.0 的核心升级理念：v7.0 解决了"能不能用"的问题，v8.0 解决"敢不敢用"和"用不用得久"的问题。**