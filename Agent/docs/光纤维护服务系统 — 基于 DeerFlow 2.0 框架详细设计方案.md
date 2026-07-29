# 光纤维护服务系统 — 基于 DeerFlow 2.0 框架详细设计方案

------

## 文档信息

| 项目     | 内容                                                         |
| -------- | ------------------------------------------------------------ |
| 文档名称 | 光纤维护服务系统 Agent 详细设计报告（DeerFlow 2.0 框架版）   |
| 版本号   | v5.0-DF                                                      |
| 基线文档 | 详细设计报告 v3.2.1 + v4.0 + 接口文档 v2.2                   |
| 框架基座 | DeerFlow 2.0（开源 AI Agent 框架）                           |
| 编制日期 | 2026-07-25                                                   |
| 变更说明 | 以 DeerFlow 2.0 框架能力为核心视角，重新组织全量设计，输出可直接指导编码的工程级方案 |

------

## 第一部分：设计总览与框架映射

### 1.1 设计目标

将光纤维护服务 Agent 的全部业务能力（数据查询、智能分析、报告生成、知识问答、批量处理、容错降级）落地到 **DeerFlow 2.0 框架**的标准扩展点上，确保：

- 所有 Agent 通过 DeerFlow 的 **Agent Registry** 注册与管理
- 所有工具通过 DeerFlow 的 **Tool Plugin** 机制定义与发现
- 所有横切关注点通过 DeerFlow 的 **Middleware Pipeline** 实现
- 所有业务流程通过 DeerFlow 的 **Markdown Skills** 编排
- 所有外部数据通过 DeerFlow 的 **MCP Connector** 接入

### 1.2 核心设计原则（6 项）

| #    | 原则           | 说明                                                         | DeerFlow 映射                                       |
| ---- | -------------- | ------------------------------------------------------------ | --------------------------------------------------- |
| P1   | Agent 不做计算 | 所有数值计算由后端完成，Agent 仅做语义理解、调度编排、结果表述 | Sub-Agent Prompt 约束 + Tool 仅返回原始数据         |
| P2   | 单一数据出口   | 所有后端数据必须经 data-collector 获取，禁止其他 Sub-Agent 直连后端 | Tool 权限隔离：仅 data-collector 注册后端 API Tools |
| P3   | 批量工程标准化 | 分块-游标-背压-幂等四要素                                    | batch_tools.py 实现，DeerFlow Tool 接口规范         |
| P4   | 确定性优先     | 分析类任务温度 0.1，确保同数据同结论                         | DeerFlow Agent Config 中 per-agent temperature      |
| P5   | 四级容错       | 正常→模型降级→规则兜底→纯知识模式                            | DeerFlow Middleware + Fallback Chain                |
| P6   | 轻量存储       | 记忆仅存关键指标快照，适配单用户 SQLite                      | DeerFlow Memory 接口 + SQLite 实现                  |

### 1.3 DeerFlow 2.0 框架能力 → 系统需求映射总表

| DeerFlow 2.0 能力       | 框架机制                          | 本系统使用方式                          |
| ----------------------- | --------------------------------- | --------------------------------------- |
| **Agent Registry**      | `agents/` 目录 + config.yaml 声明 | 注册 1 Lead + 4 Sub-Agent               |
| **Tool Plugin**         | `tools/` 目录 + `@tool` 装饰器    | 18 个自定义 Tool（fiber/）              |
| **Middleware Pipeline** | `middlewares/` 目录 + 管道配置    | 4 个中间件（Auth/Domain/RateLimit/RAG） |
| **Markdown Skills**     | `skills/` 目录 + YAML frontmatter | 5 个业务技能文件                        |
| **MCP Connector**       | `mcp/` 目录 + MCP Server          | 连接后端 REST/WS API                    |
| **Memory System**       | `memory/` 目录 + 存储抽象         | 短期(内存) + 长期(SQLite)               |
| **Plugin SDK**          | `plugins/` 目录 + 自动发现        | Tool/Agent/Skill 热加载扩展             |
| **LLM Provider**        | config.yaml `llm` 配置            | OLLAMA (qwen2.5:7b/3b/1.5b)             |
| **Observability**       | 内置 Trace/Metrics/Logging        | 全链路追踪 + Prometheus + Grafana       |

------

## 第二部分：系统架构设计

### 2.1 整体架构（DeerFlow 2.0 视角）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户交互层                                     │
│         (DeerFlow Web UI :3000 / API :8000 / Vue3 面板 :5173)       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP / WebSocket
┌──────────────────────────▼──────────────────────────────────────────┐
│              DeerFlow 2.0 Agent Runtime (:8000)                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Middleware Pipeline (DeerFlow 内置管道机制)                   │   │
│  │  ① AuthMW → ② DomainValidationMW → ③ RateLimitMW            │   │
│  │  → ④ RAGInjectionMW → Lead Agent                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Lead Agent (编排层) — DeerFlow Agent Registry 注册           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │   │
│  │  │ 意图识别  │ │ 任务分解  │ │ 调度编排  │ │ 结果聚合&表述  │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────────┘  │   │
│  │  Skills 匹配: 5 个 Markdown Skills 自动触发                   │   │
│  └───┬──────────┬──────────┬──────────┬─────────────────────────┘   │
│      │          │          │          │                              │
│  ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼──────────┐                   │
│  │ data- │ │analysis│ │report-│ │  knowledge-  │  ← Sub-Agent      │
│  │collector│ │-expert │ │generator│ │  assistant  │    (按需实例化)  │
│  └───┬───┘ └───┬───┘ └───┬───┘ └───┬──────────┘                   │
│      │          │          │          │                              │
│  ┌───▼──────────▼──────────▼──────────▼─────────────────────────┐   │
│  │  DeerFlow Tool Layer (tools/fiber/)                           │   │
│  │  18 Tools: topology(4) + performance(2) + alarm(2)           │   │
│  │  + colored(2) + stats(2) + batch(4) + rag(2)                 │   │
│  │  + export(3) + memory(2)                                     │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼───────────────────────────────────┐   │
│  │  DeerFlow MCP Connector (mcp/fiber_backend.py)               │   │
│  │  熔断器 │ 背压控制 │ 退避重试 │ 超时分级(2s/3s/5s)           │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼───────────────────────────────────┐   │
│  │  DeerFlow Memory System (memory/fiber_memory.py)             │   │
│  │  短期(内存,30条) + 长期(SQLite,指标快照<200B)                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  DeerFlow Observability (observability/)                      │   │
│  │  Tracing(SQLite) + Metrics(Prometheus) + Logging(JSON)       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                    MCP Server (独立服务 :8088)                        │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐       │
│  │ 光纤性能 API    │  │ 告警/板卡 API   │  │  RAG 知识库      │       │
│  └────────────────┘  └────────────────┘  └──────────────────┘       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│              后端业务系统 (C++ REST :8080 / WS :8081)                │
└─────────────────────────────────────────────────────────────────────┘

外部依赖:
  OLLAMA (:11434) — qwen2.5:7b / 3b / 1.5b
  ChromaDB (:8100) — RAG 向量数据库
  Prometheus (:9090) + Grafana (:3001) — 监控
```

### 2.2 DeerFlow 2.0 三级实例化模型

```
┌─────────────────────────────────────────────────────┐
│  L1 注册层（DeerFlow Agent Registry，静态常驻）       │
│  - 4 个 Sub-Agent 元数据注册于 Lead Agent            │
│  - 零资源占用，仅保存名称/描述/工具清单/温度配置      │
│  - 对应 DeerFlow config.yaml agents 配置节           │
└──────────────────────┬──────────────────────────────┘
                       │ 用户请求触发
┌──────────────────────▼──────────────────────────────┐
│  L2 执行层（DeerFlow 按需实例化/销毁）               │
│  - Lead Agent 根据意图识别结果创建对应 Sub-Agent     │
│  - 任务完成后销毁，释放上下文窗口                    │
│  - 生命周期 ≤ 单次请求                              │
└──────────────────────┬──────────────────────────────┘
                       │ 批量场景
┌──────────────────────▼──────────────────────────────┐
│  L3 批量层（DeerFlow Tool 内分块迭代）               │
│  - 单实例内按 Chunk 迭代处理（batch_tools.py）       │
│  - 每 Chunk 完成后释放中间数据                       │
│  - 禁止为每条记录创建独立 Agent 实例                 │
└─────────────────────────────────────────────────────┘
```

### 2.3 Sub-Agent 注册表（DeerFlow Agent Registry）

| Sub-Agent           | DeerFlow 注册路径             | 温度 | top_p | 模型        | 工具集                          |
| ------------------- | ----------------------------- | ---- | ----- | ----------- | ------------------------------- |
| data-collector      | `agents/data_collector/`      | 0.0  | 1.0   | primary(7b) | 14 个数据查询 Tools             |
| analysis-expert     | `agents/analysis_expert/`     | 0.1  | 0.3   | primary(7b) | memory_query, memory_save       |
| report-generator    | `agents/report_generator/`    | 0.3  | 0.8   | primary(7b) | rag_query, export_pdf/excel/csv |
| knowledge-assistant | `agents/knowledge_assistant/` | 0.5  | 0.9   | primary(7b) | rag_query, memory_query         |
| Lead Agent          | `agents/lead_agent/`          | 0.0  | 1.0   | primary(7b) | 调度上述 4 个 Sub-Agent         |

------

## 第三部分：DeerFlow Tool 层详细设计

### 3.1 Tool 目录结构（DeerFlow 标准）

```
deer-flow/backend/packages/harness/deerflow/tools/fiber/
├── __init__.py                 # Tool 自动注册入口
├── topology_tools.py           # 4 tools: fiber_connection_query, batch_fiber_connection_query, board_query, batch_board_query
├── performance_tools.py        # 2 tools: fiber_performance_query, fiber_spanloss_query
├── alarm_tools.py              # 2 tools: alarm_query, batch_alarm_query
├── colored_tools.py            # 2 tools: colored_fibers_query, all_colored_fibers_query
├── stats_tools.py              # 2 tools: fiber_stats_query, fiber_trend_query
├── batch_tools.py              # 4 tools: batch_fiber_performance_query, batch_fiber_spanloss_query, batch_alarm_query, batch_board_query
├── rag_tools.py                # 2 tools: rag_query, rag_search
├── export_tools.py             # 3 tools: export_pdf, export_excel, export_csv
└── memory_tools.py             # 2 tools: memory_save, memory_query
```

### 3.2 Tool → 后端 API 完整映射表

| DeerFlow Tool                 | 后端 REST API                       | gRPC RPC                                   | 超时 | 所属 Sub-Agent              |
| ----------------------------- | ----------------------------------- | ------------------------------------------ | ---- | --------------------------- |
| fiber_connection_query        | GET /api/v1/topology/fibers/{id}    | TopologyService.GetFiber                   | 2s   | data-collector              |
| batch_fiber_connection_query  | POST /api/v1/topology/fibers/batch  | TopologyService.BatchGetFibers             | 5s   | data-collector              |
| board_query                   | GET /api/v1/boards/{id}             | BoardService.GetBoard                      | 2s   | data-collector              |
| batch_board_query             | POST /api/v1/boards/batch           | BoardService.BatchGetBoards                | 5s   | data-collector              |
| fiber_performance_query       | GET /api/v1/fibers/{id}/performance | FiberMaintService.GetFiberPerformance      | 2s   | data-collector              |
| batch_fiber_performance_query | —                                   | FiberMaintService.BatchGetFiberPerformance | 5s   | data-collector              |
| fiber_spanloss_query          | GET /api/v1/fibers/{id}/spanloss    | FiberMaintService.GetFiberSpanloss         | 2s   | data-collector              |
| batch_fiber_spanloss_query    | —                                   | FiberMaintService.BatchGetFiberSpanloss    | 5s   | data-collector              |
| colored_fibers_query          | GET /api/v1/fibers/colored?color=X  | FiberMaintService.GetColoredFibers         | 2s   | data-collector              |
| all_colored_fibers_query      | GET /api/v1/fibers/colored/all      | FiberMaintService.GetAllColoredFibers      | 3s   | data-collector              |
| fiber_stats_query             | GET /api/v1/fibers/stats/realtime   | FiberMaintService.GetFiberStatsRealtime    | 2s   | data-collector              |
| fiber_trend_query             | GET /api/v1/fibers/stats/trend      | FiberMaintService.GetFiberStatsTrend       | 3s   | data-collector              |
| alarm_query                   | GET /api/v1/alarms/current          | AlarmService.GetCurrentAlarm               | 2s   | data-collector              |
| batch_alarm_query             | —                                   | AlarmService.BatchGetCurrentAlarms         | 5s   | data-collector              |
| rag_query                     | ChromaDB 内部                       | —                                          | 3s   | report-gen / knowledge      |
| export_pdf                    | 本地 reportlab                      | —                                          | 10s  | report-generator            |
| export_excel                  | 本地 openpyxl                       | —                                          | 10s  | report-generator            |
| export_csv                    | 本地 csv                            | —                                          | 5s   | report-generator            |
| memory_save                   | SQLite 异步写入                     | —                                          | 1s   | analysis-expert             |
| memory_query                  | SQLite 查询                         | —                                          | 1s   | analysis-expert / knowledge |

### 3.3 DeerFlow Tool 定义规范（代码示例）

```python
# tools/fiber/topology_tools.py
from deerflow.plugin import ToolPlugin, tool

class TopologyTools(ToolPlugin):
    name = "fiber_topology"
    version = "1.0.0"
    description = "光纤拓扑查询工具集"

    @tool
    async def fiber_connection_query(self, fiber_id: str) -> str:
        """查询单条连纤信息（网元间光纤连接）
        Args:
            fiber_id: 光纤编号，格式 FIB-XXXX
        Returns:
            JSON: 连纤详情（src_board, dst_board, color, scene_type）
        """
        return await self.mcp_client.get(
            f"/api/v1/topology/fibers/{fiber_id}",
            timeout=2.0
        )

    @tool
    async def batch_fiber_connection_query(
        self, fiber_ids: list[str], chunk_id: str, cursor_id: str
    ) -> str:
        """批量查询连纤信息（分块，每块≤50条）
        Args:
            fiber_ids: 光纤编号列表（≤50条/块）
            chunk_id: 块唯一标识（幂等键）
            cursor_id: 批量任务游标
        Returns:
            JSON: 批量结果（含 found/error_message 标记）
        """
        return await self.mcp_client.post(
            "/api/v1/topology/fibers/batch",
            json={"fiber_ids": fiber_ids, "chunk_id": chunk_id},
            timeout=5.0
        )
```

------

## 第四部分：DeerFlow Middleware Pipeline 设计

### 4.1 管道执行顺序（DeerFlow 内置机制）

```
请求入站 → ① AuthMW → ② DomainValidationMW → ③ RateLimitMW → ④ RAGInjectionMW → Lead Agent
```

### 4.2 各中间件详细设计

| #    | 中间件             | DeerFlow 路径                            | 职责                         | 关键配置                        |
| ---- | ------------------ | ---------------------------------------- | ---------------------------- | ------------------------------- |
| ①    | AuthMiddleware     | `middlewares/fiber/auth.py`              | 验证用户身份，注入用户上下文 | 单用户固定 token；预留 RBAC     |
| ②    | DomainValidationMW | `middlewares/fiber/domain_validation.py` | 校验领域参数合法性           | 光纤编号格式 FIB-XXXX；批量≤200 |
| ③    | RateLimitMW        | `middlewares/fiber/rate_limit.py`        | 令牌桶限流                   | 10 req/min，突发 20             |
| ④    | RAGInjectionMW     | `middlewares/fiber/rag_injection.py`     | 前置知识注入                 | 相似度≥0.6；最多3条/1000 tokens |

### 4.3 RAGInjectionMiddleware 核心逻辑

```python
# middlewares/fiber/rag_injection.py
class RAGInjectionMiddleware(DeerFlowMiddleware):
    async def process(self, request, next_handler):
        # 1. 意图判断：仅 "分析"/"报告" 类请求触发
        if request.intent not in ["analysis", "report", "diagnosis"]:
            return await next_handler(request)

        # 2. 查询改写
        rewritten_query = self.rewrite_query(request.user_message)

        # 3. 否定词过滤
        exclude_categories = self.extract_negation(rewritten_query)

        # 4. 向量检索 (ChromaDB)
        results = await self.chromadb.search(
            query=rewritten_query,
            top_k=5,
            threshold=0.6,
            exclude=exclude_categories
        )

        # 5. 截断至预算 (≤3条, ≤1000 tokens)
        injected = self.truncate_to_budget(results[:3], max_tokens=1000)

        # 6. 注入 System Prompt 末尾
        request.system_prompt += self.format_knowledge(injected)

        return await next_handler(request)
```

------

## 第五部分：DeerFlow Markdown Skills 设计

### 5.1 Skills 目录（DeerFlow 标准）

```
deer-flow/backend/packages/harness/deerflow/skills/
├── fiber_spanloss_analysis.md    # 衰耗分析
├── fiber_color_diagnosis.md      # 颜色诊断
├── batch_fiber_analysis.md       # 批量分析
├── fiber_trend_analysis.md       # 趋势分析
└── ne_health_check.md            # 网元巡检
```

### 5.2 Skill 文件格式规范（DeerFlow YAML Frontmatter）

```yaml
---
name: fiber_spanloss_analysis
description: 光纤衰耗分析完整流程
version: "1.0"
triggers: [衰耗, 光功率, spanloss, OOP, IOP, dB]
tools_required: [fiber_performance_query, fiber_spanloss_query, rag_query]
output_format: markdown
---
```

### 5.3 五大 Skill 核心流程

| #    | Skill                   | 触发词         | 执行流程                                       | 涉及 Sub-Agent                                      |
| ---- | ----------------------- | -------------- | ---------------------------------------------- | --------------------------------------------------- |
| 1    | fiber_spanloss_analysis | 衰耗/光功率/dB | 获取性能→获取衰耗→阈值判断→结论→RAG建议        | data-collector → analysis-expert                    |
| 2    | fiber_color_diagnosis   | 颜色/红色/告警 | 获取颜色→获取告警→获取性能→综合诊断→优先级建议 | data-collector → analysis-expert                    |
| 3    | batch_fiber_analysis    | 批量/所有/全部 | 获取列表→分块(4×50)→聚合→排序→共性问题         | data-collector → analysis-expert → report-generator |
| 4    | fiber_trend_analysis    | 趋势/变化/统计 | 获取趋势→获取统计→异常检测→预测→建议           | data-collector → analysis-expert                    |
| 5    | ne_health_check         | 巡检/健康/网元 | 获取关联→逐条检查→健康评分→问题清单            | data-collector → analysis-expert → report-generator |

------

## 第六部分：批量处理引擎设计（DeerFlow Tool 层实现）

### 6.1 四要素模型

| 要素                    | 实现位置                     | 核心参数                             |
| ----------------------- | ---------------------------- | ------------------------------------ |
| **分块 (Chunking)**     | `batch_tools.py`             | CHUNK_SIZE=50, MAX_CHUNKS=4          |
| **游标 (Cursor)**       | SQLite `batch_tasks` 表      | CURSOR_TTL=300s, 断点续传            |
| **背压 (Backpressure)** | MCP 连接器层                 | 错误率>10%→并发降至2, 块间延迟1000ms |
| **幂等 (Idempotency)**  | SQLite `idempotency_keys` 表 | chunk_id 去重, TTL=300s              |

### 6.2 分块处理核心流程（DeerFlow Tool 内）

```python
# tools/fiber/batch_tools.py
async def batch_process(self, fiber_ids: list, chunk_size=50):
    total = len(fiber_ids)
    assert total <= 200, "超出批量上限"
    cursor_id = generate_cursor()
    results = []

    for chunk_index, chunk in enumerate(chunked(fiber_ids, chunk_size), 1):
        chunk_id = f"{cursor_id}_chunk_{chunk_index}"

        # 1. 背压检查
        if self.backpressure.is_throttled():
            await asyncio.sleep(self.backpressure.get_wait_time())

        # 2. 幂等检查
        if self.idempotency_store.exists(chunk_id):
            results.append(self.idempotency_store.get(chunk_id))
            continue

        # 3. 调用 MCP 批量 API
        chunk_result = await self.mcp_client.post(
            "/api/v1/fibers/performance/batch",
            json={"fiber_ids": chunk, "chunk_id": chunk_id},
            timeout=5.0
        )

        # 4. 记录幂等标记
        self.idempotency_store.save(chunk_id, chunk_result, ttl=300)
        results.append(chunk_result)

        # 5. 进度上报 + 块间延迟
        await self.report_progress(chunk_index * chunk_size, total)
        await asyncio.sleep(0.2)  # 200ms

    # 6. 分层聚合（程序化统计 + Top-N 异常 → LLM 仅处理摘要）
    return self.aggregator.summarize(results)
```

### 6.3 聚合策略（解决 8K 上下文限制）

```
输入: N 条原始数据（最多 200 条）

第一层: 程序化统计（不经过 LLM，零 token 消耗）
├── 总数 / 正常数 / 异常数 / 各色占比
├── 损耗均值 / 最大值 / 最小值
└── 趋势方向（后端标记）

第二层: 异常筛选（不经过 LLM）
├── 红色光纤列表（全量）
├── 损耗突增 Top-10
└── 新增告警列表

第三层: LLM 分析（仅传入摘要 + 异常明细 ≈ 3500 tokens）
└── 输出: 分析解读 + 维护建议
```

------

## 第七部分：MCP 连接器设计（DeerFlow MCP 层）

### 7.1 部署模式

| 环境      | 部署方式             | 端口  |
| --------- | -------------------- | ----- |
| 开发/测试 | DeerFlow 进程内嵌    | —     |
| 生产      | 独立 MCP Server 容器 | :8088 |

### 7.2 超时分级 + 重试 + 熔断

| 请求类型          | 超时 | 重试策略                      | 熔断条件 |
| ----------------- | ---- | ----------------------------- | -------- |
| 单条查询          | 2s   | 5xx→退避重试2次(500ms/1000ms) | 5次/分钟 |
| 批量查询(单Chunk) | 5s   | 超时→重试1次                  | 同上     |
| 趋势查询          | 3s   | 5xx→退避重试2次               | 同上     |
| RAG 检索          | 3s   | 不重试                        | —        |

**熔断器参数**：失败阈值 5次/分钟 → 熔断 30s → 半开探测 1次/10s → 连续3次成功恢复

### 7.3 背压控制器状态机

```
NORMAL(并发=5, 延迟200ms)
    │ 错误率>10%
    ▼
THROTTLED(并发=2, 延迟1000ms)
    │ 错误率<3% 持续60s
    ▼
RECOVER(并发=3, 延迟500ms)
    │ 持续60s 错误率<3%
    ▼
NORMAL
```

------

## 第八部分：记忆系统设计（DeerFlow Memory 层）

### 8.1 双层记忆架构

| 层级     | 存储           | 容量              | 生命周期     | 写入方式 |
| -------- | -------------- | ----------------- | ------------ | -------- |
| 短期记忆 | 内存（进程内） | 最近 30 条消息    | 会话结束清除 | 同步     |
| 长期记忆 | SQLite         | 指标快照 <200B/条 | 保留 90 天   | 异步队列 |

### 8.2 去重规则

```python
def should_save(new_record, existing_record):
    if existing_record is None:
        return True   # 无历史，保存
    if new_record.color != existing_record.color:
        return True   # 颜色变化（关键事件），保存
    return False      # 颜色未变，覆盖
```

### 8.3 SQLite 表结构

```sql
CREATE TABLE memory_long_term (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fiber_id    TEXT NOT NULL,
    spanloss    REAL,
    color       TEXT CHECK(color IN ('green','yellow','red')),
    summary     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_memory_fiber_time ON memory_long_term(fiber_id, created_at);
```

------

## 第九部分：RAG 知识检索设计

### 9.1 技术配置

| 参数       | 值                      |
| ---------- | ----------------------- |
| 向量数据库 | ChromaDB (:8100)        |
| Embedding  | BAAI/bge-large-zh-v1.5  |
| Reranker   | BAAI/bge-reranker-v2-m3 |
| 分块大小   | 512 tokens / 重叠 50    |
| 混合检索   | Vector 0.6 + BM25 0.4   |
| 最终返回   | Reranker Top-3          |
| 相似度阈值 | ≥ 0.6                   |

### 9.2 知识库分类（6 类 16 篇初始文档）

| #    | Collection         | 内容                         | 文档数 |
| ---- | ------------------ | ---------------------------- | ------ |
| 1    | device_manual      | 有源盘/无源盘规格、端口约束  | 3      |
| 2    | maintenance_guide  | 巡检规范、抢修流程、安全规范 | 3      |
| 3    | alarm_guide        | 告警级别、处理流程、升级规则 | 3      |
| 4    | fault_cases        | 典型故障案例                 | 3      |
| 5    | threshold_standard | 衰耗阈值表、光功率范围       | 2      |
| 6    | ne_config          | 组网规则、配置约束           | 2      |

### 9.3 双路径检索

| 路径     | 触发方式                       | 执行者                                 |
| -------- | ------------------------------ | -------------------------------------- |
| 被动注入 | 请求前置自动（RAGInjectionMW） | 分析/报告类请求                        |
| 主动检索 | Tool 调用（rag_query）         | report-generator / knowledge-assistant |

------

## 第十部分：容错与降级设计（四级模型）

### 10.1 降级链

```
L1 正常模式（所有 LLM 可用）
    │ 主模型连续 3 次超时/5xx
    ▼
L2 模型降级: primary(7B) → fallback(3B) → fast(1.5B)
    │ 所有模型均不可用
    ▼
L3 规则兜底: 固定模板输出（白名单场景）
    │ 后端 API 也熔断
    ▼
L4 纯知识模式: 仅 RAG 知识库可访问
```

### 10.2 L3 白名单场景

| 场景             | 兜底模板                                         |
| ---------------- | ------------------------------------------------ |
| 单条光纤性能查询 | "光纤 {id} 当前损耗 {spanloss}dB，状态: {color}" |
| 红色光纤列表     | "当前红色光纤共 {n} 条: {id_list}"               |
| 实时统计         | "绿色 {g} 条 / 黄色 {y} 条 / 红色 {r} 条"        |
| 告警列表         | "当前活跃告警 {n} 条: {alarm_list}"              |

------

## 第十一部分：上下文窗口预算管理

### 11.1 预算分配（总计 8192 tokens）

| 区域          | 预算     | 优先级   | 可压缩       |
| ------------- | -------- | -------- | ------------ |
| System Prompt | 500      | 固定     | ❌            |
| 用户指令      | 300      | 固定     | ❌            |
| 输出格式约束  | 500      | 固定     | ❌            |
| **当前数据**  | **3000** | **P1**   | ✅ 聚合压缩   |
| **RAG 知识**  | **1000** | **P2**   | ✅ 减条/截断  |
| **历史记忆**  | **500**  | **P3**   | ✅ 可完全丢弃 |
| 安全余量      | 392      | 固定     | ❌            |
| **输出预留**  | **2000** | **固定** | ❌ 永不让渡   |

### 11.2 超限降级顺序

```
超预算 → 压缩P3(记忆: 3→1→0) → 压缩P2(RAG: 3→2→1→0)
       → 压缩P1(数据: 全量→聚合Top10→最小Top5)
       → 仍超限 → 拒绝执行，提示缩小范围
```

------

## 第十二部分：可观测性设计（DeerFlow Observability）

### 12.1 三支柱

| 支柱    | 实现                              | 存储                     | 保留    |
| ------- | --------------------------------- | ------------------------ | ------- |
| Tracing | DeerFlow 内置 Trace + 自定义 Span | SQLite (traces/spans 表) | 7 天    |
| Metrics | Prometheus 指标采集               | Prometheus (:9090)       | 30 天   |
| Logging | 结构化 JSON 日志                  | 文件 + Loki（可选）      | 7~30 天 |

### 12.2 核心告警规则

| 告警           | 条件                   | 级别 |
| -------------- | ---------------------- | ---- |
| LLM 不可用     | 所有模型连续 3 次失败  | P0   |
| 降级至 L3      | degradation_level = L3 | P1   |
| 后端熔断       | circuit_breaker = OPEN | P1   |
| 延迟劣化       | P95 > 30s 持续 5min    | P2   |
| Token 成本异常 | 日累计 > 500K          | P2   |

------

## 第十三部分：Prompt 版本管理

### 13.1 目录结构

```
prompts/
├── VERSION                    # 当前全局版本号
├── CHANGELOG.md
├── lead_agent/system.md + .sha256 + history/
├── analysis_expert/system.md + .sha256 + few_shots/ + history/
├── report_generator/system.md + templates/ + history/
├── knowledge_assistant/system.md + history/
├── middleware/rag_injection_template.md + l3_fallback/
└── tests/test_cases.yaml + run_regression.py
```

### 13.2 版本规范

- **major**: 角色定义/核心约束变更
- **minor**: 判定标准/输出格式调整
- **patch**: 措辞优化/typo 修复
- 变更必须走 PR + 回归测试 + 2人 review
- 运行时 SHA256 哈希校验防篡改

------

## 第十四部分：导出与报告引擎

| 格式     | 实现库                 | 用途               |
| -------- | ---------------------- | ------------------ |
| PDF      | reportlab + matplotlib | 正式报告（含图表） |
| Excel    | openpyxl               | 数据表格（可编辑） |
| CSV      | csv 模块               | 原始数据导出       |
| Markdown | 原生                   | 对话内展示         |

文件管理：存储 `/tmp/fiber_reports/`，命名 `{trace_id}_{timestamp}.{ext}`，24h 自动清理，单文件 ≤ 50MB。

------

## 第十五部分：插件化扩展架构（DeerFlow Plugin SDK）

| 插件类型        | 扩展方式                             | 热加载   |
| --------------- | ------------------------------------ | -------- |
| Tool 插件       | 放入 `plugins/tools/`，自动发现      | ✅        |
| Sub-Agent 插件  | 放入 `plugins/agents/` + config 声明 | ✅        |
| Skill 插件      | 放入 `skills/`，自动加载             | ✅        |
| Middleware 插件 | config.yaml 声明 + 代码注册          | ❌ 需重启 |

------

## 第十六部分：完整部署方案（Docker Compose）

### 16.1 服务编排（8 个容器）

| 服务          | 镜像/构建              | 端口            | 职责                  |
| ------------- | ---------------------- | --------------- | --------------------- |
| ollama        | ollama/ollama:latest   | :11434          | LLM 推理 (qwen2.5)    |
| chromadb      | chromadb/chroma:latest | :8100           | RAG 向量数据库        |
| fiber-backend | ./fiber-backend        | :8080/:8081     | C++ 后端 REST+WS      |
| mcp-server    | ./mcp-server           | :8088           | MCP 数据接入          |
| **deerflow**  | ./deer-flow            | **:8000/:3000** | **DeerFlow Agent 层** |
| frontend      | ./frontend             | :5173           | Vue3 统计面板         |
| prometheus    | prom/prometheus        | :9090           | 指标采集              |
| grafana       | grafana/grafana        | :3001           | 监控看板              |

### 16.2 启动顺序

```
ollama → chromadb → fiber-backend → mcp-server → deerflow → frontend → prometheus + grafana
```

### 16.3 环境要求

| 组件   | 要求                       |
| ------ | -------------------------- |
| CPU    | ≥ 8 核                     |
| 内存   | ≥ 32GB（推荐 64GB）        |
| 磁盘   | ≥ 500GB SSD                |
| GPU    | 可选（NVIDIA ≥ 24GB VRAM） |
| Docker | ≥ 24.0 + Compose ≥ 2.20    |

------

## 第十七部分：项目目录结构（最终版）

```
fiber-maintenance-agent/
├── deer-flow/                              # ★ DeerFlow 2.0 Agent 层
│   ├── backend/packages/harness/deerflow/
│   │   ├── agents/lead_agent/agent.py      # Lead Agent
│   │   ├── tools/fiber/                    # ★ 18 自定义 Tools
│   │   │   ├── topology_tools.py (4)
│   │   │   ├── performance_tools.py (2)
│   │   │   ├── alarm_tools.py (2)
│   │   │   ├── colored_tools.py (2)
│   │   │   ├── stats_tools.py (2)
│   │   │   ├── batch_tools.py (4)
│   │   │   ├── rag_tools.py (2)
│   │   │   ├── export_tools.py (3)
│   │   │   └── memory_tools.py (2)
│   │   ├── middlewares/fiber/              # ★ 4 Middleware
│   │   ├── skills/                         # ★ 5 Markdown Skills
│   │   ├── memory/fiber_memory.py          # 记忆系统
│   │   ├── mcp/fiber_backend.py            # MCP 连接器
│   │   ├── export/                         # PDF/Excel/CSV
│   │   ├── observability/                  # Trace/Metrics/Logging
│   │   └── plugins/                        # 插件目录
│   └── Dockerfile
├── prompts/                                # Prompt 版本管理
├── mcp-server/                             # MCP Server（独立服务）
├── knowledge_base/                         # RAG 知识库（6类）
├── frontend/                               # Vue3 统计面板
├── fiber-backend/                          # C++ 后端
├── tests/                                  # 测试 + 自测客户端
├── monitoring/                             # Prometheus + Grafana
├── docs/                                   # 文档
├── config.yaml                             # ★ 主配置
├── docker-compose.yaml                     # ★ 部署编排
├── .gitlab-ci.yml                          # CI/CD
└── Makefile
```

------

## 第十八部分：配置速查（config.yaml 核心节）

```yaml
app:
  name: fiber-maintenance-agent
  version: 5.0.0
  port: 8000

llm:
  provider: ollama
  base_url: http://ollama:11434
  models:
    primary: qwen2.5:7b
    fallback: qwen2.5:3b
    fast: qwen2.5:1.5b
  context_window: 8192

agents:
  data_collector:    { temperature: 0.0, top_p: 1.0 }
  analysis_expert:   { temperature: 0.1, top_p: 0.3, seed: 42 }
  report_generator:  { temperature: 0.3, top_p: 0.8 }
  knowledge_assistant: { temperature: 0.5, top_p: 0.9 }

batch:
  chunk_size: 50
  max_total: 200
  chunk_timeout: 5s
  inter_chunk_delay: 200ms
  cursor_ttl: 300s

mcp_server:
  port: 8088
  timeout: { single: 2s, batch: 5s, trend: 3s, rag: 3s }
  circuit_breaker: { failure_threshold: 5, window: 60s, cooldown: 30s }
  backpressure: { error_rate_threshold: 0.10, recovery_threshold: 0.03 }

rag:
  similarity_threshold: 0.6
  top_k: 5
  max_inject: 3
  max_inject_tokens: 1000

context_budget:
  total_window: 8192
  output_reserve: 2000  # 永不让渡

rate_limit: { algorithm: token_bucket, rate: 10/min, burst: 20 }
sandbox: { enabled: false }  # 设计扩展，默认关闭
```

------

## 第十九部分：开发路线图（4 周）

| 周次 | 工作                                             | 产出       | 验收标准               |
| ---- | ------------------------------------------------ | ---------- | ---------------------- |
| W11  | DeerFlow 2.0 部署 + OLLAMA + MCP 骨架 + 容错框架 | 运行环境   | 模型可调用，降级可触发 |
| W12  | 18 Tools + 4 Middleware + 单元测试               | 工具层完整 | 所有 Tool 可调用后端   |
| W13  | 4 Sub-Agent + 5 Skills + RAG 知识库              | 端到端对话 | 5 类场景可用           |
| W14  | Vue3 面板 + 导出 + 记忆 + 监控 + 联调            | 全功能     | ETCLOVG 验收通过       |

------

## 第二十部分：验收标准（ETCLOVG）

| 维度              | 验收项   | 通过标准                                  |
| ----------------- | -------- | ----------------------------------------- |
| **E**nvironment   | 环境部署 | Docker Compose 一键启动，所有服务健康     |
| **T**ools         | 工具调用 | 18 个 Tool 全部可正确调用后端 API         |
| **C**onversation  | 对话能力 | 单条/批量/趋势/巡检/知识问答 5 类场景通过 |
| **L**ogic         | 业务逻辑 | 颜色/衰耗结果与后端一致，无误判           |
| **O**utput        | 输出质量 | 报告结构完整，建议合理，引用准确          |
| **V**isualization | 可视化   | 统计面板实时刷新，趋势图正确              |
| **G**raceful      | 容错降级 | 后端断开→离线模式，模型超时→自动降级      |

------

## 附录：关键设计决策追溯

| 决策                 | 选择                    | 依据                          |
| -------------------- | ----------------------- | ----------------------------- |
| 批量处理             | 分块(50)+游标+背压+幂等 | AWS/Stripe 工程标准           |
| analysis-expert 温度 | 0.1 (非 0.3)            | 确定性/可审计/幻觉抑制/一致性 |
| Sub-Agent 数量       | 4 (非 5)                | RAG 改为中间件+按需，合理精简 |
| 记忆模型             | 指标快照 <200B          | 存储效率提升 10x              |
| 容错级别             | 四级 (非二级)           | 覆盖全故障谱                  |
| 沙箱                 | 设计扩展，默认关闭      | 评审决策，不影响基线          |
| 上下文窗口           | 8192 tokens 预算管理    | 硬约束下的资源调度            |

------

*— 文档结束 —*