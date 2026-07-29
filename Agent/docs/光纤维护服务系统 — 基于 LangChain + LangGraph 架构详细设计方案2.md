# 光纤维护服务 Agent 系统 — 工业级完整设计方案 v7.0-Final

> **文档版本**：v7.0-Final
> **编制日期**：2026-07-29
> **文档性质**：架构设计规格书 + 实现蓝图
> **适用范围**：光纤维护智能体系统的架构评审、开发实施、测试验收  

------

## 目录

- [第一部分：背景与问题定义](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第一部分背景与问题定义)
- [第二部分：设计哲学与核心原则](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第二部分设计哲学与核心原则)
- [第三部分：系统架构总览](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第三部分系统架构总览)
- [第四部分：L0 规则引擎与 Fast Path](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第四部分l0-规则引擎与-fast-path)
- [第五部分：参数防线设计](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第五部分参数防线设计)
- [第六部分：主图编排与 Controlled Loop](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第六部分主图编排与-controlled-loop)
- [第七部分：Tool 层设计](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第七部分tool-层设计)
- [第八部分：RAG 知识引擎](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第八部分rag-知识引擎)
- [第九部分：实时事件与主动诊断](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第九部分实时事件与主动诊断)
- [第十部分：降级与容错策略](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第十部分降级与容错策略)
- [第十一部分：安全设计](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第十一部分安全设计)
- [第十二部分：可观测性与审计](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第十二部分可观测性与审计)
- [第十三部分：部署方案](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第十三部分部署方案)
- [第十四部分：开发路线图与复杂度预算](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第十四部分开发路线图与复杂度预算)
- [第十五部分：验收标准](https://www.qianwen.com/chat/1d0eba4071e84e82a89b9e1f61533ad2#第十五部分验收标准)

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

**核心矛盾**：网络规模快速增长，运维人力持续缩减。传统"人盯告警、手动排查"的模式已不可持续。

### 1.2 现有系统痛点

当前光纤维护依赖 C++ 后端服务（以下简称"后端"），提供 REST API + WebSocket 接口。运维人员通过 Web 前端操作：

| 痛点         | 具体表现                                                     | 影响               |
| ------------ | ------------------------------------------------------------ | ------------------ |
| **操作复杂** | 查一条光纤需要：登录→选网元→选单盘→选端口→查连纤→查性能→查告警→人工比对 | 单次排查 5-10 分钟 |
| **信息分散** | 拓扑、性能、告警、趋势分布在不同页面，无法关联分析           | 根因定位困难       |
| **被动响应** | 只有人主动查询才能获取信息，告警来了不知道影响范围           | 故障扩大           |
| **经验依赖** | "衰耗 8dB 正不正常"取决于老师傅经验，新人无法独立判断        | 人才断层           |
| **报告低效** | 巡检报告需手动汇总数据、截图、填表                           | 一份报告 2-4 小时  |

### 1.3 项目目标

构建一个**光纤维护智能体（Agent）**，作为运维人员的"AI 助手"：

| 目标         | 量化指标                                         |
| ------------ | ------------------------------------------------ |
| 自然语言查询 | "查 FIB-0012 的衰耗" → 2 秒内返回结果            |
| 智能诊断     | "FIB-0012 为什么变红了" → 自动多步排查，给出根因 |
| 批量操作     | "查所有红色光纤" → 自动聚合统计                  |
| 主动预警     | CRITICAL 告警 → 5 秒内自动诊断并推送             |
| 报告生成     | "生成本周巡检报告" → 自动生成结构化报告          |
| 知识问答     | "什么是 OOP？" → 基于知识库回答                  |

### 1.4 技术约束

| 约束             | 说明                                          | 影响                       |
| ---------------- | --------------------------------------------- | -------------------------- |
| **数据不出网**   | 电信行业等保三级，所有数据必须在内网处理      | 必须本地部署 LLM           |
| **LLM 能力有限** | 使用 qwen2.5:7b（本地 Ollama），非 GPT-4 级别 | 不能让 LLM 做复杂推理/计算 |
| **后端不可修改** | C++ 后端已上线运行，Agent 只能作为"前端"调用  | 仅 REST + WebSocket        |
| **高可用要求**   | 7×24 运维，Agent 不可用不能影响原有系统       | 必须有完整降级链           |
| **可审计**       | 等保三级要求所有操作可追溯，日志保留 180 天   | 全链路审计                 |
| **响应时间**     | 运维人员耐心阈值 ~3 秒                        | 必须有 Fast Path           |

### 1.5 后端接口概览

后端提供 REST API（:8080）+ WebSocket（:8081），核心接口：

| 域                  | 接口数  | 关键接口                                           |
| ------------------- | ------- | -------------------------------------------------- |
| 拓扑（Topology）    | 8       | 连纤查询、场景查询、批量查询                       |
| 性能（Performance） | 6       | 光功率、历史性能、批量性能                         |
| 告警（Alarm）       | 7       | 当前告警、批量告警、PullCall                       |
| 光纤状态（Fiber）   | 6       | 连纤性能，连纤衰耗，颜色查询、统计、趋势，批量查询 |
| 设备（Board/NE）    | 6       | 单盘查询、网元查询                                 |
| **合计**            | **~33** | —                                                  |

**关键参数类型**（全部为强类型）：

| 参数       | 后端类型             | 示例                           | 约束              |
| ---------- | -------------------- | ------------------------------ | ----------------- |
| fiber_id   | **int32**            | `1001`                         | 正整数            |
| board_id   | **int32**            | `5`                            | 正整数            |
| port_id    | **int32**            | `3`                            | 正整数            |
| fiber_ids  | **repeated int32**   | `[1, 2, 999]`                  | ≤200              |
| ports      | **repeated PortRef** | `[{"board_id":5,"port_id":3}]` | 告警≤50，性能≤200 |
| color      | **enum**             | `RED` / `YELLOW`               | 仅枚举值          |
| start_time | **string**           | `"2026-07-22T00:00:00"`        | ISO 8601          |

### 1.6 通信协议分层

| 通信方向                | 协议              | 说明                              |
| ----------------------- | ----------------- | --------------------------------- |
| **Agent → API Gateway** | **REST（:8080）** | JSON 格式，JWT 认证               |
| **Agent ← WebSocket**   | **WS（:8081）**   | 实时事件推送（alarm/color/stats） |
| API Gateway → 微服务    | gRPC              | 内部，Agent 不直接接触            |
| 微服务 → 微服务         | gRPC              | 内部                              |

**结论**：Agent 作为"前端"角色，**仅通过 REST + WebSocket 访问后端**，不涉及 gRPC。

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

**这个命题的工程意义**：

- LLM 出错 → 翻译错误 → 被校验层拦截 → 追问用户（**可控**）
- LLM 不可用 → 翻译层失效 → 规则引擎兜底（**降级但可用**）
- LLM 幻觉 → 编造数据 → 但数据全部来自后端 API（**不可能编造**）

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
│                                                                   │
│   ┌──────────────── CONTROLLED LOOP ────────────────┐            │
│   │                                                  │            │
│   │   DataCollector ⇄ AnalysisExpert (ReAct ≤3)     │            │
│   │   ReportGen → ReportEval (Reflection ≤1)        │            │
│   │                                                  │            │
│   │   终止保障：                                      │            │
│   │   ① 轮次上限 (≤3)                                │            │
│   │   ② LLM 调用预算 (≤10)                           │            │
│   │   ③ 无进展检测 (action_signature)                │            │
│   │   ④ Tool 全失败熔断                              │            │
│   │                                                  │            │
│   └──────────────────────────────────────────────────┘            │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

**一句话**：缰绳在手，马可以走，但不能跑偏。

### 2.3 八条设计原则

| #      | 原则         | 含义                                           | 工程体现               |
| ------ | ------------ | ---------------------------------------------- | ---------------------- |
| **P1** | LLM 只做翻译 | 判断由规则引擎，计算由程序，LLM 仅做语言转换   | judgment/narrator 分离 |
| **P2** | 确定性优先   | 能用规则解决的不用 LLM，能用程序的不用规则     | L0 规则引擎前置        |
| **P3** | 单一数据出口 | 仅 data_collector 子图可调用后端 API           | Tool 绑定隔离          |
| **P4** | 受控 Loop    | 允许回环但必须有四重终止保障                   | continue_loop 函数     |
| **P5** | 参数不可信   | 用户输入经三层校验 + 两道断言才能到达后端      | Parameter Gate         |
| **P6** | 梯度降级     | 保核心推理，砍非关键修饰；不是每步都用规则替代 | L0-L4 降级链           |
| **P7** | 事件驱动     | 既响应主动查询，也响应实时事件触发自动诊断     | WebSocket + Proactive  |
| **P8** | 全链路可审计 | 每个请求从输入到输出完整记录，满足等保三级     | audit_trail + LangFuse |

### 2.4 响应时间 SLA 分级

| 路径              | 触发条件               | 目标延迟  | 实现手段                   |
| ----------------- | ---------------------- | --------- | -------------------------- |
| **Fast Path**     | L0 规则命中 + 单条查询 | **< 1s**  | 规则引擎 + 直接 API + 模板 |
| **Normal Path**   | L0 未命中 + LLM 识别   | **< 5s**  | LLM 意图 + API + LLM 表述  |
| **Heavy Path**    | 批量 / 报告 / 复杂分析 | **< 15s** | Send 并发 + 流式输出       |
| **Degraded Path** | LLM/后端不可用         | **< 2s**  | 规则兜底 + 缓存 + 模板     |

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
│  │  │(安全过滤) │  │(L0快速)  │  │(参数校验) │  │(条件路由)        │ │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┬─────────┘ │ │
│  │                                                      │           │ │
│  │  ┌───────────────────────────────────────────────────▼─────────┐ │ │
│  │  │                    SubGraph Zone                             │ │ │
│  │  │                                                             │ │ │
│  │  │  ┌─────────────────── Controlled Loop ──────────────────┐  │ │
│  │  │  │                                                      │  │ │
│  │  │  │  DataCollector ⇄ RuleJudgment → Narrator             │  │ │
│  │  │  │       (ReAct ≤3, 四重终止)                            │  │ │
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
│  │  │  EventTrigger → QuickCollect → AutoAnalyze → Alert/Report   │ │ │
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
│  │(23 Tools │ │(nomic-   │ │(PG Check │ │(3-Layer  │ │(SQLite +     │ │
│  │REST-only)│ │embed+BM25│ │pointer)  │ │+2 Assert)│ │TTL 5min)     │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      基础设施层 (Infrastructure Layer)                    │
│                                                                         │
│  ┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐│
│  │Ollama  │ │PostgreSQL│ │Redis   │ │LangFuse│ │Prometheus│ │C++ 后端││
│  │(LLM +  │ │(Checkpoint│ │(Event  │ │(Trace +│ │+ Grafana │ │REST    ││
│  │Embed)  │ │+ Audit)  │ │Queue)  │ │Audit)  │ │(Metrics) │ │:8080   ││
│  └────────┘ └──────────┘ └────────┘ └────────┘ └──────────┘ └────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 技术选型

| 组件         | 选型                             | 版本        | 理由                                              |
| ------------ | -------------------------------- | ----------- | ------------------------------------------------- |
| LLM          | qwen2.5:7b                       | Ollama 0.6+ | 本地部署，数据不出网，中文能力强                  |
| Embedding    | nomic-embed-text                 | Ollama 内置 | 与 LLM 统一运维，8192 上下文，768 维              |
| 编排框架     | LangGraph                        | ≥0.4        | 原生 StateGraph + Send + interrupt + Checkpointer |
| LLM 框架     | LangChain                        | ≥0.3        | Tool/Prompt/Memory 生态                           |
| 向量库       | ChromaDB（MVP）→ Milvus（生产）  | ≥0.6        | 轻量启动，生产扩展                                |
| Checkpointer | PostgreSQL                       | 16          | 并发支持，审计日志同库                            |
| 事件队列     | Redis Streams                    | 7           | WebSocket 事件缓冲 + 发布订阅                     |
| 本地缓存     | SQLite（aiosqlite）              | —           | 零依赖，L4 离线兜底                               |
| HTTP 客户端  | httpx.AsyncClient                | ≥0.27       | 连接池 + 异步 + 超时控制                          |
| 可观测       | LangFuse（主）+ Prometheus（辅） | —           | Trace + Metrics 双支柱                            |
| 定时任务     | APScheduler                      | ≥3.10       | 轻量，无需 Celery                                 |
| 部署         | Docker Compose                   | —           | MVP 5 容器，生产 8 容器                           |

### 3.3 项目目录结构

```
fiber-agent/
├── src/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理
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
│   │   ├── rule_engine.py         # L0 规则引擎
│   │   ├── param_gate.py          # 参数校验关卡
│   │   ├── intent_classifier.py   # LLM 意图识别
│   │   ├── rule_judgment.py       # 规则判断（程序化）
│   │   ├── narrator.py            # LLM 表述（仅翻译）
│   │   ├── report_generator.py    # 报告生成
│   │   ├── report_evaluator.py    # 报告评估（Reflection）
│   │   ├── clarification.py       # 追问（interrupt）
│   │   └── degradation.py         # 降级处理
│   ├── tools/
│   │   ├── _http_client.py        # HTTP 客户端（连接池+熔断）
│   │   ├── fiber_tools.py         # 光纤查询 Tool
│   │   ├── alarm_tools.py         # 告警查询 Tool
│   │   ├── performance_tools.py   # 性能查询 Tool
│   │   ├── topology_tools.py      # 拓扑查询 Tool
│   │   ├── stats_tools.py         # 统计/趋势 Tool
│   │   ├── event_tools.py         # 事件查询 Tool
│   │   └── pullcall_tools.py      # PullCall Tool
│   ├── rag/
│   │   ├── engine.py              # RAG 引擎（nomic + BM25）
│   │   ├── ingest.py              # 文档入库（中英文标注）
│   │   ├── query_rewriter.py      # Query 改写
│   │   └── knowledge_base/        # 知识库文档
│   ├── events/
│   │   ├── listener.py            # WebSocket 监听器
│   │   └── router.py              # 事件路由规则
│   ├── cache/
│   │   └── local_cache.py         # SQLite 本地缓存
│   ├── security/
│   │   ├── input_guard.py         # Prompt 注入检测
│   │   └── output_filter.py       # 敏感信息脱敏
│   ├── observability/
│   │   ├── metrics.py             # Prometheus 指标
│   │   ├── audit.py               # 审计日志
│   │   └── tracing.py             # LangFuse 集成
│   └── resilience/
│       ├── circuit_breaker.py     # 熔断器
│       ├── degradation.py         # 降级管理器
│       └── health_probe.py        # 健康探测
├── tests/
│   ├── golden_set/                # 50 条 Golden Set
│   ├── test_rule_engine.py
│   ├── test_param_gate.py
│   ├── test_loop.py
│   └── test_degradation.py
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

------

## 第四部分：L0 规则引擎与 Fast Path

### 4.1 设计动机

基于电信运维工单统计，**78% 的日常查询是模式化的**：

| 模式         | 占比    | 示例                 |
| ------------ | ------- | -------------------- |
| 单条光纤查询 | 35%     | "查光纤1001的衰耗"   |
| 告警查询     | 20%     | "5号盘3口有什么告警" |
| 颜色查询     | 12%     | "现在有哪些红色光纤" |
| 统计查询     | 11%     | "光纤总数多少"       |
| **合计**     | **78%** | —                    |

如果每次都走 LLM 意图识别（2-4s），系统响应时间不可接受。

### 4.2 规则引擎设计

```python
# src/nodes/rule_engine.py

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class RuleMatch:
    """规则匹配结果"""
    intent: str                    # 识别到的意图
    params: dict                   # 提取的参数（已标准化）
    confidence: float              # 置信度（规则命中 = 1.0）
    template_id: str               # 输出模板 ID
    fast_path_eligible: bool       # 是否可走 Fast Path（单条+无Loop）


class RuleEngine:
    """
    L0 规则引擎：基于正则 + 关键词的确定性意图识别。
    
    设计原则：
    - 零 LLM 调用，纯程序化
    - 延迟 < 10ms
    - 只处理高置信度的模式化查询
    - 未命中时返回 None，交由 LLM 处理
    """
    
    # ===== 规则定义（25-30 条）=====
    
    RULES = [
        # --- 单条光纤查询 ---
        {
            "id": "R001",
            "pattern": r'(?:查|看|查询)\s*(?:光纤|FIB)[-_]?(\d+)\s*(?:的)?\s*(?:衰耗|spanloss|损耗)',
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
        
        # --- 端口告警查询 ---
        {
            "id": "R010",
            "pattern": r'(\d+)\s*号?\s*(?:盘|单盘|板)\s*(\d+)\s*号?\s*(?:口|端口)\s*(?:的)?\s*(?:告警|alarm)',
            "intent": "port_alarm_query",
            "param_extract": lambda m: {"board_id": int(m.group(1)), "port_id": int(m.group(2))},
            "template": "T_PORT_ALARM",
            "fast_path": True,
        },
        
        # --- 颜色查询 ---
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
        
        # --- 统计查询 ---
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
        
        # --- 知识问答（关键词触发）---
        {
            "id": "R040",
            "pattern": r'(?:什么是|解释|定义|含义)\s*(.{2,20})',
            "intent": "knowledge_qa",
            "param_extract": lambda m: {"question": m.group(1)},
            "template": "T_KNOWLEDGE",
            "fast_path": False,  # RAG 需要 LLM 组织回答
        },
    ]
    
    @classmethod
    def match(cls, user_input: str) -> Optional[RuleMatch]:
        """
        尝试规则匹配。命中返回 RuleMatch，未命中返回 None。
        时间复杂度：O(n)，n = 规则数（~30），延迟 < 10ms。
        """
        text = user_input.strip()
        
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
                    )
                except (ValueError, IndexError):
                    continue  # 参数提取失败，尝试下一条规则
        
        return None  # 未命中，交由 LLM
```

### 4.3 Fast Path 端到端流程

```
用户: "查光纤1001的衰耗"
         │
         ▼ (~0ms)
┌─ InputGuard ─────────────────────────────────────────┐
│  正则扫描 → 无注入 → PASS                             │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~5ms)
┌─ RuleEngine ─────────────────────────────────────────┐
│  命中 R001                                           │
│  intent = "spanloss_query"                           │
│  params = {"fiber_id": 1001}                         │
│  fast_path = True                                    │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~3ms)
┌─ ParamGate ──────────────────────────────────────────┐
│  fiber_id = 1001 → int ✅ → gt(0) ✅ → PASS          │
└──────────────────────────────────────────────────────┘
         │
         ▼ (~150ms)
┌─ DirectAPI ──────────────────────────────────────────┐
│  GET /api/v1/fibers/1001/spanloss                    │
│  Response: {"fiber_id":1001, "spanloss":3.2, ...}   │
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
总耗时: ~160ms ← Fast Path 目标 < 1s ✅
LLM 调用: 0 次
Token 消耗: 0
```

### 4.4 规则引擎在主图中的位置

```python
# 主图边定义（关键部分）

graph.set_entry_point("input_guard")
graph.add_edge("input_guard", "rule_engine")

# 规则引擎 → 条件路由
graph.add_conditional_edges(
    "rule_engine",
    route_after_rule_engine,
    {
        "fast_path": "fast_path_executor",     # 规则命中 + 单条 → 直接执行
        "rule_hit": "param_gate",              # 规则命中 + 复杂 → 参数校验后正常流程
        "rule_miss": "intent_classifier",      # 未命中 → LLM 意图识别
    }
)

def route_after_rule_engine(state: MainGraphState) -> str:
    match = state.get("rule_match")
    if match is None:
        return "rule_miss"
    if match.fast_path_eligible:
        return "fast_path"
    return "rule_hit"
```

### 4.5 规则引擎维护机制

| 机制           | 说明                                             |
| -------------- | ------------------------------------------------ |
| **配置化**     | 规则存储在 YAML 文件中，非硬编码                 |
| **热更新**     | 修改规则文件后无需重启，通过 API 触发重载        |
| **命中率监控** | Prometheus 指标 `rule_engine_hit_total{rule_id}` |
| **未命中分析** | 每周统计 LLM 识别的高频意图，评估是否新增规则    |
| **回归测试**   | 每次规则变更后跑 Golden Set（50 条），确保无退化 |

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
    
    # ===== 格式转换正则 =====
    
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
    
    # ===== 主入口 =====
    
    @classmethod
    def validate_and_normalize(cls, raw: dict) -> NormalizedParams:
        """
        Layer 2: 校验 + 标准化。
        
        Returns:
            NormalizedParams（强类型，与后端 int32/enum 对齐）
        """
        failures = []
        
        # 光纤 ID
        fiber_ids = []
        for ref in raw.get("fiber_refs", []):
            fid = cls._extract_id(ref, cls._FIBER_PATTERNS)
            if fid is not None and fid > 0:
                fiber_ids.append(fid)
            else:
                failures.append(f"无法识别光纤标识: '{ref}'（示例: FIB-0012 或 12号光纤）")
        
        # 批量上限
        if len(fiber_ids) > 200:
            failures.append(f"批量上限 200 条，当前 {len(fiber_ids)} 条")
            fiber_ids = fiber_ids[:200]
        
        # 单盘 ID
        board_ids = []
        for ref in raw.get("board_refs", []):
            bid = cls._extract_id(ref, cls._BOARD_PATTERNS)
            if bid is not None and bid > 0:
                board_ids.append(bid)
            else:
                failures.append(f"无法识别单盘标识: '{ref}'（示例: 5号盘）")
        
        # 端口 ID
        port_ids = []
        for ref in raw.get("port_refs", []):
            pid = cls._extract_id(ref, cls._PORT_PATTERNS)
            if pid is not None and pid > 0:
                port_ids.append(pid)
            else:
                failures.append(f"无法识别端口标识: '{ref}'（示例: 3口）")
        
        # 构建 PortRef
        port_refs = []
        if board_ids and port_ids:
            if len(board_ids) == len(port_ids):
                port_refs = [{"board_id": b, "port_id": p}
                             for b, p in zip(board_ids, port_ids)]
            else:
                failures.append("单盘和端口数量不匹配")
        
        # 颜色
        color = None
        color_ref = raw.get("color_ref")
        if color_ref:
            color = cls._COLOR_MAP.get(color_ref.strip().lower(),
                    cls._COLOR_MAP.get(color_ref.strip()))
            if color is None:
                failures.append(f"无法识别颜色: '{color_ref}'（仅支持: 红/黄/绿）")
        
        # 时间
        start_time, end_time = cls._parse_time(raw.get("time_expression", ""))
        
        return NormalizedParams(
            fiber_ids=fiber_ids,
            board_ids=board_ids,
            port_ids=port_ids,
            port_refs=port_refs,
            color=color,
            start_time=start_time,
            end_time=end_time,
            ne_id=raw.get("ne_id"),
            parse_failures=failures,
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
        
        # "最近N天/周/月"
        m = re.search(r'最近\s*(\d+)\s*(天|日|周|星期|月)', expr)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            delta = {'天': timedelta(days=n), '日': timedelta(days=n),
                     '周': timedelta(weeks=n), '星期': timedelta(weeks=n),
                     '月': timedelta(days=n*30)}[unit]
            return ((now - delta).strftime("%Y-%m-%dT00:00:00"),
                    now.strftime("%Y-%m-%dT%H:%M:%S"))
        
        # "X月X日到X日"
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
    
    优势：
    - State 被 Checkpointer 保存，服务重启不丢失
    - 恢复时跳过 input_guard（已校验过）
    - 用户回复也可能命中规则引擎
    """
    params = state["normalized_params"]
    failures = params.parse_failures
    
    # 构建追问消息
    question_parts = ["抱歉，以下信息我没能正确识别：\n"]
    for f in failures:
        question_parts.append(f"  • {f}")
    question_parts.append("\n请补充说明，例如：")
    question_parts.append("  • 光纤编号：FIB-0012 或 12号光纤")
    question_parts.append("  • 单盘端口：5号盘3口")
    question_parts.append("  • 颜色：红色 / 黄色")
    question_parts.append("  • 时间：最近一周 / 7月22日到29日")
    
    # interrupt() 暂停图执行，等待用户输入
    user_reply = interrupt({
        "question": "\n".join(question_parts),
        "missing_params": failures,
    })
    
    # 用户回复后，跳回 rule_engine（而非从头开始）
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


# ========== 强类型模型 ==========

class NormalizedParams(BaseModel):
    """标准化参数 — 与后端 int32/enum/string 严格对齐"""
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
    """规则判断结果 — 程序化生成，非 LLM"""
    status: Literal["NORMAL", "WARNING", "CRITICAL"]
    findings: list[str]          # 程序化判断条目
    metrics: dict                # 关键数值（供 Narrator 引用）
    suggested_actions: list[str] # 建议操作


class AnalysisVerdict(BaseModel):
    """分析结论 — LLM 辅助判断"""
    conclusion: str
    severity: Literal["NORMAL", "WARNING", "CRITICAL"]
    evidence: list[str]
    confidence: float = Field(ge=0, le=1)
    need_more_data: bool = False
    additional_query: Optional[dict] = None


class LoopRecord(BaseModel):
    """Loop 审计记录"""
    loop_number: int
    reason: str
    tool_requested: str
    action_signature: str  # hash(action + observation)，用于无进展检测
    timestamp: str


# ========== 主图 State ==========

class MainGraphState(TypedDict):
    # 对话
    messages: Annotated[list[BaseMessage], add_messages]
    thread_id: str
    user_input: str
    
    # 规则引擎
    rule_match: Optional[dict]           # RuleMatch 序列化
    fast_path_result: Optional[str]      # Fast Path 直接输出
    
    # 意图与参数
    intent: Optional[str]
    raw_extractions: Optional[dict]
    normalized_params: Optional[NormalizedParams]
    
    # Loop 控制
    loop_count: int
    max_loops: int                       # 默认 3
    llm_call_count: int                  # LLM 调用总计数
    max_llm_calls: int                   # 默认 10
    no_progress_count: int               # 无进展计数
    last_action_signature: Optional[str]
    loop_history: Annotated[list[dict], operator.add]
    
    # 数据（仅存摘要）
    collected_data_summary: Optional[str]
    rule_judgment: Optional[RuleJudgment]
    analysis_verdict: Optional[AnalysisVerdict]
    
    # 降级
    degradation_level: int               # 0=正常, 1-4=降级
    
    # 审计
    request_id: str
    audit_trail: Annotated[list[dict], operator.add]
    
    # 元数据
    token_budget_remaining: int
    session_start_time: str
    processing_path: str                 # "fast" / "normal" / "heavy" / "degraded"
```

### 6.2 主图构建

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
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("report_evaluator", report_evaluator_node)
    graph.add_node("batch_dispatcher", batch_dispatcher_node)
    graph.add_node("knowledge_qa", knowledge_qa_subgraph)
    graph.add_node("result_aggregator", result_aggregator_node)
    graph.add_node("degradation_handler", degradation_handler_node)
    
    # ===== 边定义 =====
    graph.set_entry_point("input_guard")
    graph.add_edge("input_guard", "rule_engine")
    
    # 规则引擎 → 三路分流
    graph.add_conditional_edges(
        "rule_engine",
        route_after_rule_engine,
        {
            "fast_path": "fast_path_executor",
            "rule_hit_complex": "param_gate",
            "rule_miss": "intent_classifier",
        }
    )
    
    # Fast Path → 直接结束
    graph.add_edge("fast_path_executor", "result_aggregator")
    
    # LLM 意图识别 → 参数校验
    graph.add_edge("intent_classifier", "param_gate")
    
    # 参数校验 → 追问 or 路由
    graph.add_conditional_edges(
        "param_gate",
        route_after_param_gate,
        {
            "need_clarification": "clarification",
            "params_ok": "intent_router",
        }
    )
    
    # 追问（interrupt 内部处理恢复）
    # clarification_node 内部使用 Command(goto="rule_engine")
    
    # 意图路由 → 各子图
    graph.add_node("intent_router", intent_router_node)  # 纯路由
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
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
    
    # analysis → 四路分流（Loop 核心）
    graph.add_conditional_edges(
        "analysis_expert",
        route_after_analysis,
        {
            "need_more_data": "data_collector",      # ReAct 回环
            "generate_report": "report_generator",   # 报告
            "direct_narrate": "narrator",            # 简单回答
            "degraded": "degradation_handler",       # 降级
        }
    )
    
    # Narrator → 聚合
    graph.add_edge("narrator", "result_aggregator")
    
    # ===== Reflection Loop =====
    graph.add_edge("report_generator", "report_evaluator")
    graph.add_conditional_edges(
        "report_evaluator",
        route_after_evaluation,
        {
            "pass": "result_aggregator",
            "refine": "report_generator",  # ≤1 次修正
        }
    )
    
    # 批量 / 知识 / 降级 → 聚合
    graph.add_edge("batch_dispatcher", "result_aggregator")
    graph.add_edge("knowledge_qa", "result_aggregator")
    graph.add_edge("degradation_handler", "result_aggregator")
    
    # 聚合 → 结束
    graph.add_edge("result_aggregator", END)
    
    # ===== 编译 =====
    checkpointer = AsyncPostgresSaver.from_conn_string(POSTGRES_URI)
    return graph.compile(checkpointer=checkpointer)
```

### 6.3 核心路由函数（四重终止保障）

```python
# src/graph/routing.py

import hashlib


def route_after_analysis(state: MainGraphState) -> str:
    """
    ReAct Loop 核心路由 — 四重终止保障。
    
    终止条件（任一满足即停止 Loop）：
    ① 轮次上限: loop_count >= max_loops (3)
    ② LLM 预算: llm_call_count >= max_llm_calls (10)
    ③ 无进展: no_progress_count >= 2
    ④ Tool 全失败: 所有 API 返回错误
    """
    verdict = state.get("analysis_verdict")
    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)
    llm_calls = state.get("llm_call_count", 0)
    max_llm_calls = state.get("max_llm_calls", 10)
    no_progress = state.get("no_progress_count", 0)
    degradation = state.get("degradation_level", 0)
    
    # 熔断：降级模式不允许 Loop
    if degradation >= 2:
        return "degraded"
    
    # ① 轮次上限
    if loop_count >= max_loops:
        return _exit_loop(state, verdict)
    
    # ② LLM 调用预算
    if llm_calls >= max_llm_calls:
        return _exit_loop(state, verdict)
    
    # ③ 无进展检测
    if no_progress >= 2:
        return _exit_loop(state, verdict)
    
    # ④ Tool 全失败（从 data_summary 判断）
    data_summary = state.get("collected_data_summary", "")
    if data_summary and all("错误" in line for line in data_summary.split("\n") if line.strip()):
        return "degraded"
    
    # LLM 判断：是否需要补充数据
    if verdict and verdict.need_more_data and verdict.additional_query:
        return "need_more_data"
    
    return _exit_loop(state, verdict)


def _exit_loop(state: MainGraphState, verdict) -> str:
    """Loop 结束后的出口选择"""
    intent = state.get("intent", "")
    
    # 简单查询 → 直接叙述
    if intent in ("spanloss_query", "connection_query", "performance_query",
                  "port_alarm_query", "colored_query", "stats_query"):
        return "direct_narrate"
    
    # 复杂分析 → 生成报告
    return "generate_report"


def compute_action_signature(action: str, observation: str) -> str:
    """计算 action + observation 的哈希，用于无进展检测"""
    content = f"{action}|{observation[:500]}"  # 截取前 500 字符
    return hashlib.md5(content.encode()).hexdigest()


def route_after_evaluation(state: MainGraphState) -> str:
    """Reflection Loop 路由 — 最多 1 次修正"""
    eval_result = state.get("_report_eval", {})
    refinement_count = eval_result.get("refinement_count", 0)
    
    if eval_result.get("passed", True):
        return "pass"
    if refinement_count >= 1:
        return "pass"  # 强制通过
    return "refine"
```

### 6.4 判断/表述分离（核心设计）

```python
# src/nodes/rule_judgment.py

"""
规则判断节点：程序化判断，零 LLM。
将原始数据转换为结构化判断结论。
"""

from src.graph.state import MainGraphState, RuleJudgment


# 领域阈值常量
SPANLOSS_THRESHOLD = 5.0      # dB
OOP_RANGE = (-8.0, -2.0)     # dBm
IOP_RANGE = (-15.0, -8.0)    # dBm


async def rule_judgment_node(state: MainGraphState) -> dict:
    """
    程序化判断：根据阈值规则生成结构化结论。
    LLM 不参与此环节。
    """
    import json
    
    data_summary = state.get("collected_data_summary", "")
    findings = []
    metrics = {}
    status = "NORMAL"
    
    # 解析数据摘要中的关键指标
    # （实际实现中从 tool_results 原始 JSON 解析）
    for line in data_summary.split("\n"):
        if "spanloss" in line.lower():
            # 提取衰耗值
            import re
            m = re.search(r'spanloss[=:]\s*([\d.]+)', line)
            if m:
                spanloss = float(m.group(1))
                metrics["spanloss"] = spanloss
                if spanloss > SPANLOSS_THRESHOLD:
                    findings.append(
                        f"衰耗 {spanloss}dB 超过阈值 {SPANLOSS_THRESHOLD}dB（超出 "
                        f"{((spanloss - SPANLOSS_THRESHOLD) / SPANLOSS_THRESHOLD * 100):.0f}%）"
                    )
                    status = "CRITICAL" if spanloss > 8.0 else "WARNING"
                else:
                    findings.append(f"衰耗 {spanloss}dB，在阈值 {SPANLOSS_THRESHOLD}dB 内，正常")
        
        elif "告警" in line or "alarm" in line.lower():
            m = re.search(r'CRITICAL[=:]\s*(\d+)', line)
            if m and int(m.group(1)) > 0:
                findings.append(f"存在 {m.group(1)} 条 CRITICAL 告警")
                status = "CRITICAL"
    
    # 建议操作
    suggested_actions = []
    if status == "CRITICAL":
        suggested_actions.append("立即派单检修")
        suggested_actions.append("检查关联光纤是否受影响")
    elif status == "WARNING":
        suggested_actions.append("列入下次巡检计划")
        suggested_actions.append("持续监控趋势变化")
    
    judgment = RuleJudgment(
        status=status,
        findings=findings,
        metrics=metrics,
        suggested_actions=suggested_actions,
    )
    
    return {"rule_judgment": judgment}
# src/nodes/narrator.py

"""
叙述节点：LLM 仅做"翻译"——将结构化判断转换为自然语言。
硬约束：不得修改任何数值，不得添加 judgment 中没有的判断。
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
    """LLM 叙述：仅翻译，不判断"""
    from langchain_core.messages import AIMessage
    
    judgment = state.get("rule_judgment")
    if not judgment:
        return {"messages": [AIMessage(content="暂无分析结果。")]}
    
    response = await (narrator_prompt | narrator_llm).ainvoke({
        "question": state["user_input"],
        "status": judgment.status,
        "findings": "\n".join(f"  • {f}" for f in judgment.findings),
        "metrics": str(judgment.metrics),
        "actions": "、".join(judgment.suggested_actions) or "无",
    })
    
    return {
        "messages": [AIMessage(content=response.content)],
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }
```

### 6.5 analysis_expert（Loop 推理环节）

```python
# src/nodes/analysis_expert.py

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from src.graph.state import MainGraphState, AnalysisVerdict, LoopRecord
from src.graph.routing import compute_action_signature
from datetime import datetime


analysis_llm = ChatOllama(
    model="qwen2.5:7b", temperature=0.1, seed=42,
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
2. 关键信息缺失（如：有告警但不知影响范围）→ need_more_data = true
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
    """分析专家 — ReAct Loop 推理环节"""
    
    loop_count = state.get("loop_count", 0)
    judgment = state.get("rule_judgment")
    
    # 构建判断文本
    judgment_text = "无" if not judgment else (
        f"状态: {judgment.status}\n"
        f"发现: {'; '.join(judgment.findings)}\n"
        f"指标: {judgment.metrics}"
    )
    
    # 循环历史
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
    
    # 无进展检测
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
        
        # 记录审计
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

### 6.6 主图可视化

```
                         ┌──────────────┐
                         │  input_guard │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                         │ rule_engine  │
                         └──┬───┬───┬───┘
                            │   │   │
              fast_path ────┘   │   └──── rule_miss
                   │            │              │
          ┌────────▼───┐  ┌────▼────┐  ┌──────▼──────────┐
          │fast_path   │  │param    │  │intent_classifier│
          │_executor   │  │_gate    │  │(LLM)            │
          └────────┬───┘  └────┬────┘  └──────┬──────────┘
                   │           │               │
                   │     ┌─────▼─────┐         │
                   │     │需要追问？  │         │
                   │     └──┬─────┬──┘         │
                   │        │     │            │
                   │   YES  │     │ NO         │
                   │  ┌─────▼──┐  │            │
                   │  │clarif. │  │            │
                   │  │(inter- │  │            │
                   │  │ rupt)  │  │            │
                   │  └────────┘  │            │
                   │              │            │
                   │         ┌────▼────────────▼────┐
                   │         │    intent_router      │
                   │         └──┬──┬──┬──┬──────────┘
                   │            │  │  │  │
                   │     ┌──────┘  │  │  └──────┐
                   │     │         │  │         │
                   │  ┌──▼──┐  ┌──▼──▼──┐  ┌───▼────┐
                   │  │batch│  │data    │  │knowl.  │
                   │  │disp.│  │collect.│  │_qa     │
                   │  └──┬──┘  └───┬────┘  └───┬────┘
                   │     │         │            │
                   │     │  ┌──────▼──────┐     │
                   │     │  │rule_judgment│     │
                   │     │  │(程序化)     │     │
                   │     │  └──────┬──────┘     │
                   │     │         │            │
                   │     │  ┌──────▼──────┐     │
                   │     │  │analysis     │     │
                   │     │  │_expert(LLM) │     │
                   │     │  └──┬──┬──┬──┬─┘     │
                   │     │     │  │  │  │       │
                   │     │     │  │  │  └─degraded
                   │     │     │  │  │     │    │
                   │     │  ┌──▼──┘  │  ┌──▼────▼──┐
                   │     │  │need_   │  │degradation│
                   │     │  │more    │  │_handler   │
                   │     │  │data    │  └─────┬─────┘
                   │     │  │(回环)  │        │
                   │     │  └───┬────┘        │
                   │     │      │             │
                   │     │      └──→ data_coll.│
                   │     │                    │
                   │     │  ┌─────────────┐   │
                   │     │  │direct_narrate│   │
                   │     │  │(LLM翻译)    │   │
                   │     │  └──────┬──────┘   │
                   │     │         │          │
                   │     │  ┌──────▼──────┐   │
                   │     │  │report_gen.  │   │
                   │     │  └──────┬──────┘   │
                   │     │         │          │
                   │     │  ┌──────▼──────┐   │
                   │     │  │report_eval. │   │
                   │     │  └──┬───────┬──┘   │
                   │     │     │       │      │
                   │     │  pass│    refine   │
                   │     │     │    (≤1次)    │
                   │     │     │       │      │
                   └─────┼─────┼───────┼──────┼──┐
                         │     │       │      │  │
                         └─────┼───────┼──────┘  │
                               │       │         │
                        ┌──────▼───────▼─────────▼──┐
                        │     result_aggregator      │
                        └──────────────┬─────────────┘
                                       │
                                      END
```

------

## 第七部分：Tool 层设计

### 7.1 Tool 清单（REST-only，与后端 v2.3 对齐）

| #    | Tool 名称                   | 后端 API                                  | 方法   | 关键参数                              | 上限 |
| ---- | --------------------------- | ----------------------------------------- | ------ | ------------------------------------- | ---- |
| 1    | `fiber_connection_query`    | `/api/v1/topology/fibers/{id}`            | GET    | fiber_id: **int**                     | —    |
| 2    | `fiber_scene_query`         | `/api/v1/topology/fibers/{id}/scene`      | GET    | fiber_id: **int**                     | —    |
| 3    | `fiber_performance_query`   | `/api/v1/fibers/{id}/performance`         | GET    | fiber_id: **int**                     | —    |
| 4    | `fiber_history_performance` | `/api/v1/fibers/{id}/performance/history` | GET    | fiber_id: **int**, start/end: **str** | —    |
| 5    | `fiber_spanloss_query`      | `/api/v1/fibers/{id}/spanloss`            | GET    | fiber_id: **int**                     | —    |
| 6    | `batch_fiber_query`         | `/api/v1/topology/fibers/batch`           | POST   | fiber_ids: **list[int]**              | ≤200 |
| 7    | `alarm_query`               | `/api/v1/alarms/current`                  | GET    | board_id: **int**, port_id: **int**   | —    |
| 8    | `batch_alarm_query`         | `/api/v1/alarms/current/batch`            | POST   | ports: **list[PortRef]**              | ≤50  |
| 9    | `colored_fibers_query`      | `/api/v1/fibers/colored`                  | GET    | color: **Literal["RED","YELLOW"]**    | —    |
| 10   | `fiber_stats_query`         | `/api/v1/fibers/stats`                    | GET    | —                                     | —    |
| 11   | `fiber_trend_query`         | `/api/v1/fibers/stats/trend`              | GET    | start/end: **str (ISO8601)**          | —    |
| 12   | `board_query`               | `/api/v1/boards/{id}`                     | GET    | board_id: **int**                     | —    |
| 13   | `board_fibers_query`        | `/api/v1/boards/{id}/fibers`              | GET    | board_id: **int**                     | —    |
| 14   | `batch_board_query`         | `/api/v1/boards/batch`                    | POST   | board_ids: **list[int]**              | ≤200 |
| 15   | `batch_performance_query`   | `/api/v1/fibers/performance/batch`        | POST   | ports: **list[PortRef]**              | ≤200 |
| 16   | `ne_query`                  | `/api/v1/nes/{id}`                        | GET    | ne_id: **int**                        | —    |
| 17   | `pull_call_create`          | `/api/v1/alarms/pull-call`                | POST   | ne_id: **int**                        | —    |
| 18   | `pull_call_poll`            | `/api/v1/alarms/pull-call/{task_id}`      | GET    | task_id: **str**                      | —    |
| 19   | `pull_call_cancel`          | `/api/v1/alarms/pull-call/{task_id}`      | DELETE | task_id: **str**                      | —    |
| 20   | `event_query`               | 内部 Redis                                | —      | channel: **str**, limit: **int**      | ≤50  |
| 21   | `cache_query`               | 内部 SQLite                               | —      | key: **str**                          | —    |
| 22   | `audit_query`               | 内部 PostgreSQL                           | —      | request_id: **str**                   | —    |
| 23   | `system_health`             | 内部探测                                  | —      | —                                     | —    |

### 7.2 HTTP Client（连接池 + 熔断 + 错误转换）

```python
# src/tools/_http_client.py

import httpx
import json
import time
from typing import Optional


class FiberHttpClient:
    """
    后端 REST API 客户端。
    - 连接池复用
    - 熔断器（连续 3 次失败 → 熔断 30s）
    - 400/404 错误转为结构化 Tool 响应
    - JWT Token 注入
    - 异步缓存写入（不阻塞主流程）
    """
    
    def __init__(
        self,
        base_url: str,
        max_connections: int = 20,
        max_keepalive: int = 10,
        timeout_default: float = 3.0,
        jwt_token: Optional[str] = None,
    ):
        self.base_url = base_url
        self.timeout_default = timeout_default
        self._client = httpx.AsyncClient(
            base_url=base_url,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
            ),
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
        # 熔断检查
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
                # 异步写入缓存（不阻塞）
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
        """异步写入本地缓存（L4 降级时使用）"""
        try:
            from src.cache.local_cache import LocalCache
            await LocalCache.set(path, response_text, ttl=300)  # 5min TTL
        except Exception:
            pass  # 缓存失败不影响主流程
    
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

### 7.3 Tool 实现示例

```python
# src/tools/fiber_tools.py

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
from src.tools._http_client import FiberHttpClient

client = FiberHttpClient(base_url="http://cpp-backend:8080")


# ===== 单条光纤衰耗查询 =====
class SpanlossInput(BaseModel):
    fiber_id: int = Field(gt=0, description="光纤ID（正整数），如 1001")

@tool(args_schema=SpanlossInput)
async def fiber_spanloss_query(fiber_id: int) -> str:
    """查询单条光纤的衰耗值。
    参数: fiber_id — 光纤ID（正整数）
    返回: 衰耗数据 JSON（含 spanloss 值，单位 dB）"""
    # Layer 3 断言（最后防线）
    assert isinstance(fiber_id, int) and fiber_id > 0, f"非法 fiber_id: {fiber_id}"
    return await client.get(f"/api/v1/fibers/{fiber_id}/spanloss")


# ===== 端口告警查询 =====
class AlarmInput(BaseModel):
    board_id: int = Field(gt=0, description="单盘ID（正整数）")
    port_id: int = Field(gt=0, description="端口ID（正整数）")

@tool(args_schema=AlarmInput)
async def alarm_query(board_id: int, port_id: int) -> str:
    """查询指定端口的当前活跃告警。
    参数: board_id — 单盘ID, port_id — 端口ID
    返回: 告警列表 JSON"""
    assert isinstance(board_id, int) and board_id > 0
    assert isinstance(port_id, int) and port_id > 0
    return await client.get("/api/v1/alarms/current",
                           params={"board_id": board_id, "port_id": port_id})


# ===== 批量告警（PortRef 结构 + ≤50）=====
class PortRef(BaseModel):
    board_id: int = Field(gt=0)
    port_id: int = Field(gt=0)

class BatchAlarmInput(BaseModel):
    ports: list[PortRef] = Field(max_length=50, description="端口列表，最多50个")

@tool(args_schema=BatchAlarmInput)
async def batch_alarm_query(ports: list[dict]) -> str:
    """批量查询多端口告警（上限50）。
    参数: ports — [{"board_id":5,"port_id":3}, ...]"""
    assert len(ports) <= 50, f"告警批量上限50，当前{len(ports)}"
    return await client.post("/api/v1/alarms/current/batch", json_body={"ports": ports})


# ===== 颜色查询（枚举约束）=====
class ColoredInput(BaseModel):
    color: Literal["RED", "YELLOW"] = Field(description="仅 RED 或 YELLOW")

@tool(args_schema=ColoredInput)
async def colored_fibers_query(color: str) -> str:
    """按颜色查询光纤。参数: color — RED 或 YELLOW"""
    assert color in ("RED", "YELLOW"), f"非法颜色: {color}"
    return await client.get("/api/v1/fibers/colored", params={"color": color})


# ===== 趋势查询（时间参数）=====
class TrendInput(BaseModel):
    start_time: Optional[str] = Field(default=None, description="ISO 8601，如 2026-07-22T00:00:00")
    end_time: Optional[str] = Field(default=None, description="ISO 8601")

@tool(args_schema=TrendInput)
async def fiber_trend_query(start_time: Optional[str] = None, end_time: Optional[str] = None) -> str:
    """查询光纤颜色变化趋势。参数: start_time/end_time — ISO 8601（可选）"""
    params = {}
    if start_time:
        datetime.fromisoformat(start_time)  # 校验格式
        params["start_time"] = start_time
    if end_time:
        datetime.fromisoformat(end_time)
        params["end_time"] = end_time
    return await client.get("/api/v1/fibers/stats/trend", params=params)
```

------

## 第八部分：RAG 知识引擎

### 8.1 架构

```
用户: "什么是OOP？"
         │
         ▼
┌─ Query Rewriter（LLM，可选）─────────────────────────────────────┐
│  "什么是OOP" → "OOP 输出光功率 optical power 定义 含义 正常范围"   │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Hybrid Retriever ───────────────────────────────────────────────┐
│  ┌─────────────────┐  ┌─────────────────┐                       │
│  │ Vector Search   │  │ BM25 Search     │                       │
│  │ (nomic-embed)   │  │ (关键词匹配)     │                       │
│  │ weight: 0.4     │  │ weight: 0.6     │                       │
│  │ k=5, thresh=0.45│  │ k=5             │                       │
│  └────────┬────────┘  └────────┬────────┘                       │
│           └──────────┬─────────┘                                │
│                      ▼                                          │
│           EnsembleRetriever (RRF 融合)                           │
│           Top-3 文档                                             │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ LLM 生成回答 ───────────────────────────────────────────────────┐
│  Context: [检索到的 3 段文档]                                     │
│  Prompt: "基于以下知识回答用户问题，不得编造..."                    │
│  输出: 自然语言回答 + 引用来源                                     │
└──────────────────────────────────────────────────────────────────┘
```

### 8.2 配置

```python
# src/rag/engine.py

from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever


# Embedding: nomic-embed-text (768维, 8192上下文, Ollama 统一部署)
embeddings = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url="http://ollama:11434",
)

# 向量检索
vectorstore = Chroma(
    collection_name="fiber_knowledge",
    embedding_function=embeddings,
    persist_directory="data/chromadb",
)
vector_retriever = vectorstore.as_retriever(
    search_kwargs={"k": 5, "score_threshold": 0.45}
)

# BM25 检索（中文关键词，不依赖 Embedding 质量）
bm25_retriever = BM25Retriever.from_documents(all_documents, k=5)

# 混合检索：BM25 权重更高（弥补 nomic 中文弱点）
hybrid_retriever = EnsembleRetriever(
    retrievers=[vector_retriever, bm25_retriever],
    weights=[0.4, 0.6],  # BM25 优先
)
```

### 8.3 中文检索质量补偿措施

| #    | 措施                     | 说明                                         |
| ---- | ------------------------ | -------------------------------------------- |
| 1    | **BM25 权重 0.6**        | 关键词匹配不受 Embedding 中文能力影响        |
| 2    | **文档中英文标注**       | 入库时追加：`"衰耗（spanloss/attenuation）"` |
| 3    | **Query 改写**           | LLM 将中文 query 扩展为中英混合              |
| 4    | **score_threshold 0.45** | nomic 分数分布与 bge 不同，需下调            |
| 5    | **检索质量测试集**       | 30+ 条 query→doc 映射，每次变更跑 Recall@3   |

### 8.4 文档预处理

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

def preprocess_for_ingest(text: str) -> str:
    """为中文文档追加英文关键词标注"""
    annotations = [f"{cn}({en})" for cn, en in TERM_ANNOTATIONS.items() if cn in text]
    if annotations:
        text += f"\n[关键词: {', '.join(annotations)}]"
    return text
```

------

## 第九部分：实时事件与主动诊断

### 9.1 架构

```
C++ 后端 :8081 (WebSocket)
         │
         │ ws://host:8081/ws/v1/events
         ▼
┌─────────────────────────────────────────────────────────┐
│              EventListener Service（常驻协程）             │
│                                                         │
│  订阅: alarm / fiber_color / fiber_stats                 │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Event Router（规则引擎）             │   │
│  │                                                 │   │
│  │  IF alarm.level == CRITICAL                     │   │
│  │    → 触发 Proactive Diagnosis                   │   │
│  │                                                 │   │
│  │  IF color_change: GREEN → RED                   │   │
│  │    → 触发 Proactive Diagnosis                   │   │
│  │                                                 │   │
│  │  IF stats_update                                │   │
│  │    → 写入 Redis + 更新本地缓存                   │   │
│  │                                                 │   │
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
                      ▼ (CRITICAL 事件)
┌─────────────────────────────────────────────────────────┐
│           Proactive Diagnosis SubGraph                   │
│                                                         │
│  EventTrigger → QuickCollect → AutoAnalyze → Alert      │
│                                                         │
│  特点：                                                  │
│  - 无用户交互，全自动                                    │
│  - 超时 10s（比用户查询更紧）                             │
│  - 结果推送到 WebSocket / 邮件 / 工单系统                 │
└─────────────────────────────────────────────────────────┘
```

### 9.2 EventListener 实现

```python
# src/events/listener.py

import asyncio
import json
import websockets
import redis.asyncio as redis
from datetime import datetime
from loguru import logger


class FiberEventListener:
    WS_URL = "ws://cpp-backend:8081/ws/v1/events"
    CHANNELS = ["alarm", "fiber_color", "fiber_stats"]
    
    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis = redis.from_url(redis_url)
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
        
        # 所有事件写入 Redis
        await self.redis.xadd(
            f"events:{channel}",
            {"data": json.dumps(payload), "ts": datetime.now().isoformat()},
            maxlen=1000,
        )
        
        # 规则路由
        if channel == "alarm" and payload.get("type") == "ALARM_RAISED":
            if payload.get("level") in ("CRITICAL", "MAJOR"):
                await self._trigger_proactive(payload)
        
        elif channel == "fiber_color" and payload.get("type") == "COLOR_CHANGED":
            if payload.get("old_color") == "GREEN" and payload.get("new_color") == "RED":
                await self._trigger_proactive(payload)
        
        elif channel == "fiber_stats":
            # 更新本地缓存
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
        logger.info("触发主动诊断: fiber_id={}", payload.get("fiber_id"))
```

------

## 第十部分：降级与容错策略

### 10.1 设计原则

> **保核心推理，砍非关键修饰。** 降级不是"每步都用规则替代"，而是"保住数据获取能力，简化分析表述"。

### 10.2 五级降级链

| 级别   | 触发条件                      | 策略                              | 用户感知                   | 响应时间 |
| ------ | ----------------------------- | --------------------------------- | -------------------------- | -------- |
| **L0** | 正常                          | 完整流程（规则+LLM+Loop）         | 无                         | < 5s     |
| **L1** | 7B 响应 > 10s 或连续 2 次超时 | 关闭 Loop，简化 Prompt            | 回答略简略                 | < 3s     |
| **L2** | 7B 完全不可用                 | 切换 3B 模型，关闭 Reflection     | 质量下降                   | < 4s     |
| **L3** | 所有模型不可用                | **保留 Tool 查询** + 规则模板输出 | "数据已查到，分析暂不可用" | < 2s     |
| **L4** | 后端也不可用                  | 本地缓存 + 纯 RAG + 明确告知      | "后端离线，提供缓存数据"   | < 1s     |

### 10.3 降级管理器

```python
# src/resilience/degradation.py

import asyncio
import time
from enum import IntEnum


class DegradationLevel(IntEnum):
    NORMAL = 0
    L1_SIMPLIFIED = 1
    L2_SMALL_MODEL = 2
    L3_NO_LLM = 3
    L4_OFFLINE = 4


class DegradationManager:
    """
    降级管理器：
    - 根据健康探测结果自动调整级别
    - 每 30s 后台探测，尝试恢复
    - 降级/恢复事件写入审计日志
    """
    
    def __init__(self):
        self.level = DegradationLevel.NORMAL
        self._last_change = time.time()
        self._probe_task = None
    
    async def start_probing(self):
        """后台健康探测协程（30s 间隔）"""
        while True:
            await asyncio.sleep(30)
            await self._probe()
    
    async def _probe(self):
        """探测各组件健康状态"""
        llm_ok = await self._probe_ollama()
        backend_ok = await self._probe_backend()
        
        new_level = self._compute_level(llm_ok, backend_ok)
        
        if new_level != self.level:
            old = self.level
            self.level = new_level
            self._last_change = time.time()
            logger.info(f"降级级别变更: {old.name} → {new_level.name}")
            # 写入审计
            await audit_log("degradation_change", {
                "from": old.name, "to": new_level.name
            })
    
    def _compute_level(self, llm_ok: bool, backend_ok: bool) -> DegradationLevel:
        if llm_ok and backend_ok:
            return DegradationLevel.NORMAL
        if not llm_ok and backend_ok:
            return DegradationLevel.L3_NO_LLM
        if llm_ok and not backend_ok:
            return DegradationLevel.L1_SIMPLIFIED  # LLM 可用但后端慢
        return DegradationLevel.L4_OFFLINE
    
    async def _probe_ollama(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("http://ollama:11434/api/tags")
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

### 10.4 本地缓存（L4 兜底）

```python
# src/cache/local_cache.py

import aiosqlite
import json
import time
from typing import Optional


class LocalCache:
    """
    SQLite 本地缓存。
    - 每次 API 成功响应后异步写入
    - WebSocket STATS_UPDATED 事件触发更新
    - L4 降级时返回缓存 + "数据可能不是最新" 提示
    """
    
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
                return None  # 过期
            return value
    
    @classmethod
    async def get_with_staleness(cls, key: str) -> tuple[Optional[str], bool]:
        """获取缓存，即使过期也返回（标记为 stale）"""
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

### 11.1 四层安全架构

| 层         | 措施                     | 实现                                  |
| ---------- | ------------------------ | ------------------------------------- |
| **输入层** | Prompt 注入检测          | 正则 + 关键词黑名单                   |
| **认证层** | JWT 透传                 | HTTP Client 注入 Authorization Header |
| **执行层** | Tool 白名单 + 写操作确认 | 子图隔离 + interrupt()                |
| **输出层** | 敏感信息脱敏             | IP/端口按角色脱敏                     |

### 11.2 Prompt 注入防护

```python
# src/security/input_guard.py

import re

INJECTION_PATTERNS = [
    r'忽略(以上|之前|所有)(指令|提示|规则|设定)',
    r'ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)',
    r'你(现在|从现在起)是(?!.*光纤)',  # "你现在是..." 但排除 "你现在是光纤专家"
    r'act\s+as\s+(if|though)',
    r'pretend\s+(you|to\s+be)',
    r'(system|系统)\s*prompt',
    r'删除(所有|全部|一切)(光纤|数据|记录|配置)',
    r'DROP\s+TABLE',
    r'<script',
]

WHITELIST_PATTERNS = [
    r'光纤', r'衰耗', r'告警', r'单盘', r'端口', r'网元',
    r'巡检', r'报告', r'OOP', r'IOP', r'spanloss',
]


async def input_guard_node(state: MainGraphState) -> dict:
    """输入安全过滤"""
    user_input = state.get("user_input", "")
    
    # 注入检测
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, user_input, re.IGNORECASE):
            return {
                "messages": [AIMessage(
                    content="⚠️ 检测到异常输入，已拦截。如有正常需求请重新描述。"
                )],
                "processing_path": "blocked",
            }
    
    # 长度限制
    if len(user_input) > 2000:
        user_input = user_input[:2000]
    
    return {"user_input": user_input}
```

### 11.3 写操作确认

```python
# 对于 PullCall 等写操作，使用 interrupt() 要求人工确认

@tool
async def pull_call_create(ne_id: int) -> str:
    """创建 PullCall 任务（主动拉取告警）。⚠️ 此操作会触发设备上报。"""
    # 人工确认
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

| 支柱        | 工具                 | 关注点                                       |
| ----------- | -------------------- | -------------------------------------------- |
| **Tracing** | LangFuse             | 每次对话完整 Trace：意图→参数→Tool→Loop→输出 |
| **Metrics** | Prometheus + Grafana | P99 延迟、Loop 分布、降级率、Token 消耗      |
| **Audit**   | PostgreSQL（独立表） | 等保三级：身份、操作、结果、180 天保留       |

### 12.2 关键 Metrics

```python
# src/observability/metrics.py

from prometheus_client import Counter, Histogram, Gauge

# 请求
request_total = Counter("agent_request_total", "请求总数", ["path", "intent"])
request_latency = Histogram("agent_request_latency_seconds", "请求延迟",
                           ["path"], buckets=[0.1, 0.5, 1, 2, 5, 10, 15, 30])

# 规则引擎
rule_hit_total = Counter("agent_rule_engine_hit_total", "规则命中", ["rule_id"])
rule_miss_total = Counter("agent_rule_engine_miss_total", "规则未命中")

# Tool
tool_calls_total = Counter("agent_tool_calls_total", "Tool调用", ["tool", "status"])
tool_latency = Histogram("agent_tool_latency_seconds", "Tool延迟", ["tool"])

# Loop
loop_iterations = Histogram("agent_loop_iterations", "Loop次数", buckets=[0,1,2,3])
loop_no_progress = Counter("agent_loop_no_progress_total", "无进展终止")

# 降级
degradation_level = Gauge("agent_degradation_level", "当前降级级别")
degradation_transitions = Counter("agent_degradation_transitions_total", "降级变更", ["from", "to"])

# Token
token_usage = Counter("agent_token_usage_total", "Token消耗", ["node"])

# 参数
param_failures = Counter("agent_param_failures_total", "参数解析失败", ["type"])
```

### 12.3 审计日志（等保三级）

```python
# src/observability/audit.py

import uuid
from datetime import datetime


async def write_audit_log(
    request_id: str,
    user_id: str,
    action: str,
    input_text: str,
    processing_path: str,
    api_calls: list[dict],
    output_text: str,
    token_used: int,
    latency_ms: float,
    degradation_level: int,
):
    """
    写入审计日志（PostgreSQL）。
    保留 180 天，满足等保三级要求。
    """
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO audit_logs (
                request_id, user_id, action, input_text,
                processing_path, api_calls, output_text,
                token_used, latency_ms, degradation_level,
                created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """,
            request_id, user_id, action, input_text,
            processing_path, json.dumps(api_calls), output_text,
            token_used, latency_ms, degradation_level,
            datetime.now(),
        )
```

**审计日志表结构**：

```sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL UNIQUE,
    user_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,          -- 'query' / 'diagnosis' / 'report'
    input_text TEXT NOT NULL,
    processing_path VARCHAR(16) NOT NULL,  -- 'fast' / 'normal' / 'heavy' / 'degraded'
    api_calls JSONB,                       -- [{"tool":"...", "latency_ms":..., "status":"..."}]
    output_text TEXT,
    token_used INTEGER DEFAULT 0,
    latency_ms FLOAT NOT NULL,
    degradation_level SMALLINT DEFAULT 0,
    loop_count SMALLINT DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_audit_user ON audit_logs(user_id, created_at DESC);
CREATE INDEX idx_audit_time ON audit_logs(created_at DESC);

-- 自动清理（180天）
-- 通过 pg_cron 或应用层定时任务
```

------

## 第十三部分：部署方案

### 13.1 MVP 阶段（5 容器）

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
            - capabilities: [gpu]  # 如有 GPU
    # 启动后: ollama pull qwen2.5:7b && ollama pull nomic-embed-text

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
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru

  chromadb:
    image: chromadb/chroma:latest
    volumes: [chroma_data:/chroma/chroma]
    ports: ["8100:8000"]

  agent:
    build: .
    ports: ["8000:8000"]
    depends_on: [ollama, postgres, redis, chromadb]
    environment:
      OLLAMA_URL: http://ollama:11434
      POSTGRES_URI: postgresql+asyncpg://postgres:${PG_PASSWORD}@postgres/fiber_agent
      REDIS_URL: redis://redis:6379
      CHROMA_URL: http://chromadb:8000
      BACKEND_URL: http://cpp-backend:8080
      WS_URL: ws://cpp-backend:8081/ws/v1/events
      LANGFUSE_PUBLIC_KEY: ${LANGFUSE_KEY}
      LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET}
    volumes:
      - ./data:/app/data
      - ./config:/app/config

volumes:
  ollama_data:
  pg_data:
  chroma_data:
```

### 13.2 生产阶段（+3 容器）

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
```

### 13.3 资源估算

| 组件           | CPU        | 内存       | 磁盘       | 备注               |
| -------------- | ---------- | ---------- | ---------- | ------------------ |
| Ollama (7B)    | 4 核       | 16 GB      | 10 GB      | GPU 可选（推荐）   |
| Ollama (Embed) | 1 核       | 2 GB       | 1 GB       | 与 LLM 共享进程    |
| Agent          | 2 核       | 4 GB       | 1 GB       | Python 异步        |
| PostgreSQL     | 1 核       | 2 GB       | 10 GB      | Checkpoint + Audit |
| Redis          | 0.5 核     | 512 MB     | —          | 事件队列           |
| ChromaDB       | 1 核       | 2 GB       | 5 GB       | 向量库             |
| **合计**       | **~10 核** | **~27 GB** | **~27 GB** | 单节点可部署       |

------

## 第十四部分：开发路线图与复杂度预算

### 14.1 代码量预算

| 模块                            | 代码量        | 占比     | 说明                |
| ------------------------------- | ------------- | -------- | ------------------- |
| 规则引擎 (rule_engine.py)       | ~800 行       | 12%      | 25-30 条规则 + 模板 |
| Tool 层 (23 个 Tool)            | ~1,200 行     | 18%      | 含 HTTP Client      |
| 参数关卡 (param_gate.py)        | ~400 行       | 6%       | 正则 + 校验         |
| 主图 + 路由                     | ~600 行       | 9%       | StateGraph + 条件边 |
| 子图 (data_collector 等)        | ~800 行       | 12%      | 4 个子图            |
| 节点 (analysis/narrator/report) | ~700 行       | 11%      | LLM 节点            |
| RAG 引擎                        | ~500 行       | 8%       | 检索 + 入库 + 改写  |
| 事件系统                        | ~400 行       | 6%       | WebSocket + Redis   |
| 降级 + 缓存 + 熔断              | ~500 行       | 8%       | 容错层              |
| 安全 + 审计 + 可观测            | ~400 行       | 6%       | 横切关注点          |
| 配置 + 入口 + 工具              | ~300 行       | 4%       | 胶水代码            |
| **合计**                        | **~6,600 行** | **100%** | —                   |

> "约束 LLM"的代码（规则引擎+参数关卡+降级+安全）占 **32%**，"业务功能"占 **49%**，"基础设施"占 **19%**。

### 14.2 开发路线图（6 周）

| 周次   | 目标                   | 交付物                                                       | 验收标准                              |
| ------ | ---------------------- | ------------------------------------------------------------ | ------------------------------------- |
| **W1** | 骨架 + Fast Path       | 主图 + InputGuard + RuleEngine + ParamGate + 5 个核心 Tool + HTTP Client | "查光纤1001衰耗" Fast Path < 1s       |
| **W2** | LLM 路径 + Loop        | IntentClassifier + DataCollector + RuleJudgment + AnalysisExpert + Narrator + 四重终止 | "FIB-0012为什么变红" 触发 2 轮 Loop   |
| **W3** | 批量 + RAG + 记忆      | Send 并发 + nomic-embed RAG + PG Checkpointer + 多轮对话     | 批量 200 条 < 15s；RAG Recall@3 > 80% |
| **W4** | 事件 + 主动诊断 + 缓存 | WebSocket Listener + Redis + Proactive SubGraph + SQLite Cache + L4 降级 | CRITICAL 告警 → 5s 内自动诊断         |
| **W5** | 安全 + 审计 + 报告     | Prompt 注入防护 + 审计日志 + Reflection Loop + 报告模板 + PDF 导出 | 安全测试通过；审计可查询              |
| **W6** | 联调 + 压测 + 验收     | 端到端联调 + Golden Set 回归 + 并发压测 + 文档               | 5 类核心场景全部通过                  |

### 14.3 风险与缓解

| 风险                        | 概率 | 影响 | 缓解                                      |
| --------------------------- | ---- | ---- | ----------------------------------------- |
| 7B 模型意图识别准确率不足   | 中   | 高   | L0 规则引擎覆盖 78%；剩余用 few-shot 提升 |
| nomic-embed-text 中文检索差 | 中   | 中   | BM25 权重 0.6 + 英文标注 + Query 改写     |
| 后端接口变更                | 低   | 高   | Tool 层抽象隔离；接口版本化               |
| Loop 死循环                 | 低   | 中   | 四重终止保障 + 无进展检测                 |
| 并发性能不足                | 中   | 中   | 连接池 + Send 并发 + 批量 API             |

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

| 指标            | 目标     | 测试方法             |
| --------------- | -------- | -------------------- |
| Fast Path P99   | < 1s     | 100 次规则命中请求   |
| Normal Path P99 | < 5s     | 100 次 LLM 路径请求  |
| Heavy Path P99  | < 15s    | 50 次批量 200 条请求 |
| 并发吞吐        | ≥ 10 QPS | locust 压测          |
| 主动诊断延迟    | < 5s     | 模拟 CRITICAL 事件   |

### 15.3 可靠性验收

| 指标           | 目标               | 测试方法            |
| -------------- | ------------------ | ------------------- |
| LLM 不可用降级 | 30s 内切换 L3      | 停止 Ollama 容器    |
| 后端不可用降级 | 30s 内切换 L4      | 断开后端网络        |
| Loop 终止      | 100% 在 3 轮内终止 | 构造死循环场景      |
| 服务重启恢复   | 对话不丢失         | 杀 agent 进程后重启 |
| 熔断恢复       | 30s 后自动探测     | 模拟后端 500        |

### 15.4 安全验收

| 测试项                       | 通过标准           |
| ---------------------------- | ------------------ |
| Prompt 注入（20 条攻击样本） | 100% 拦截          |
| 未认证访问                   | 返回 401           |
| 越权操作（写操作无确认）     | 被 interrupt 拦截  |
| 审计日志完整性               | 所有请求可追溯     |
| 敏感信息脱敏                 | 输出无明文 IP/密码 |

------

## 附录 A：与历史版本对比

| 维度      | v5.0           | v6.0-Industrial | v7.0-LangGraph      | **v7.0-Final（本文）**                 |
| --------- | -------------- | --------------- | ------------------- | -------------------------------------- |
| 架构模式  | Chain          | Agent + Loop    | Agent + Loop        | **Agent + Harness + Controlled Loop**  |
| LLM 定位  | "做语言"       | "只做翻译"      | "只做翻译"          | **"只做翻译"（判断/表述分离）**        |
| 响应性能  | 无约束         | SLA 分级        | SLA 分级            | **SLA 分级 + L0 规则引擎**             |
| Loop 终止 | 三重           | 三重            | 四重                | **四重（+无进展检测）**                |
| 参数校验  | 四层（有重叠） | 三层            | 三层                | **三层 + 两道断言**                    |
| 追问机制  | 返回 END       | —               | interrupt + Command | **interrupt + Command(goto)**          |
| 缓存      | 无             | SQLite + L4     | —                   | **SQLite + TTL + L4 离线**             |
| 审计      | LangFuse       | 等保三级        | audit_trail         | **PG 审计表 + LangFuse + 180 天**      |
| 事件系统  | 无             | WebSocket       | —                   | **WebSocket + Redis + Proactive**      |
| RAG       | bge-large-zh   | nomic-embed     | nomic-embed         | **nomic-embed + BM25(0.6) + 英文标注** |
| 代码量    | 未估算         | ~5800 行        | 未估算              | **~6600 行（含预算）**                 |
| 开发周期  | 4 周           | 5 周            | 5 周                | **6 周（含联调压测）**                 |

------

## 附录 B：关键设计决策记录（ADR）

| #       | 决策                                   | 理由                   | 替代方案       | 否决原因               |
| ------- | -------------------------------------- | ---------------------- | -------------- | ---------------------- |
| ADR-001 | REST-only，不用 gRPC                   | Agent 是"前端"角色     | 增加 gRPC 适配 | 协议分层明确，无需穿透 |
| ADR-002 | nomic-embed-text 而非 bge-large-zh     | 与 Ollama 统一运维     | bge-large-zh   | 需额外 2GB 依赖链      |
| ADR-003 | BM25 权重 0.6 > Vector 0.4             | nomic 中文弱           | Vector 0.6     | 中文术语检索不准       |
| ADR-004 | PostgreSQL 而非 SQLite 做 Checkpointer | 并发 + 审计同库        | SQLite         | 不支持并发写           |
| ADR-005 | 判断/表述分离                          | LLM 不可信做判断       | LLM 端到端分析 | 幻觉风险               |
| ADR-006 | L0 规则引擎前置                        | 78% 请求无需 LLM       | 全部走 LLM     | 响应时间不可接受       |
| ADR-007 | Loop 最多 3 轮                         | 工业 SLA 约束          | 无限 Loop      | 无法承诺响应时间       |
| ADR-008 | interrupt() 追问                       | State 持久化，重启不丢 | 返回 END       | 上下文丢失             |
| ADR-009 | 本地 SQLite 缓存                       | L4 离线兜底            | 无缓存         | 网络分区时完全不可用   |
| ADR-010 | 审计日志 180 天                        | 等保三级               | 7 天           | 不合规                 |

------

## 附录 C：术语表

| 术语                 | 含义                                                   |
| -------------------- | ------------------------------------------------------ |
| **Harness**          | 包裹 LLM 的工程化控制结构（图结构+Schema+降级+审计）   |
| **Controlled Loop**  | 在 Harness 约束内的有限回环（ReAct ≤3, Reflection ≤1） |
| **Fast Path**        | 规则引擎命中后的极速响应路径（< 1s，零 LLM）           |
| **Parameter Gate**   | 参数校验关卡（格式转换+业务规则+枚举校验）             |
| **Rule Judgment**    | 程序化判断（基于阈值规则，非 LLM）                     |
| **Narrator**         | LLM 叙述节点（仅翻译，不判断）                         |
| **ReAct**            | Reason-Act-Observe 循环                                |
| **Reflection**       | 生成-评估-修正 循环                                    |
| **action_signature** | action+observation 的哈希，用于无进展检测              |
| **PortRef**          | {board_id, port_id} 对象，告警/性能批量查询的参数结构  |
| **PullCall**         | 主动拉取告警机制（向设备发起轮询）                     |
| **等保三级**         | 信息安全等级保护第三级（电信行业强制要求）             |

------

> **文档结束**
>
> 本方案的核心信念：**在通信运维领域，"可靠"比"聪明"重要一万倍。** 一个每次都能在 1 秒内给出正确答案的系统，远胜于一个偶尔惊艳但经常犯错的系统。LLM 是锦上添花，不是雪中送炭。规则引擎、参数校验、降级链、审计日志——这些"无聊"的工程工作，才是工业级 Agent 的真正护城河。