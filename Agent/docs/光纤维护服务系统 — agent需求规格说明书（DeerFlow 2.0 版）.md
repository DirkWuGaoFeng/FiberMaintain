# 光纤维护服务系统 — Agent 需求规格说明书（最终版 v3.0）

> **文档版本**: v3.0 Final
> **编制日期**: 2026-07-21
> **状态**: 已确认，待实施
> **适用框架**: DeerFlow 2.0（最新版）
> **后端服务**: C++ 微服务集群（已实现）

------

## 目录

1. [项目概述](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#1-项目概述)
2. [系统架构](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#2-系统架构)
3. [Agent 层设计](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#3-agent-层设计)
4. [Tools 定义](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#4-tools-定义)
5. [Middleware 设计](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#5-middleware-设计)
6. [Markdown Skills](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#6-markdown-skills)
7. [RAG 知识库](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#7-rag-知识库)
8. [前端统计面板](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#8-前端统计面板)
9. [导出与报告](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#9-导出与报告)
10. [记忆系统](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#10-记忆系统)
11. [Python 自测客户端](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#11-python-自测客户端)
12. [知识库管理界面](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#12-知识库管理界面)
13. [监控与日志](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#13-监控与日志)
14. [异常处理与容错](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#14-异常处理与容错)
15. [插件化扩展架构](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#15-插件化扩展架构)
16. [部署方案](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#16-部署方案)
17. [CI/CD 集成](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#17-cicd-集成)
18. [非功能性需求](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#18-非功能性需求)
19. [开发路线图](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#19-开发路线图)
20. [验收标准（ETCLOVG）](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#20-验收标准etclovg)
21. [附录](https://www.qianwen.com/chat/c24988f18cee4aafb8980bfdad23cd6e#21-附录)

------

## 1. 项目概述

### 1.1 项目背景

光纤维护服务系统为通信网络运维提供智能化光纤质量分析能力。后端 C++ 微服务集群已完成核心业务逻辑（性能采集、衰耗计算、颜色判定、告警管理、统计趋势），Agent 层作为智能交互入口，通过自然语言对话为运维人员提供分析、诊断、报告生成等能力。

### 1.2 核心定位

| 层级              | 职责                                       | 技术栈                        |
| ----------------- | ------------------------------------------ | ----------------------------- |
| **后端 C++ 服务** | 业务逻辑、数据计算、颜色判定、告警管理     | C++ / gRPC / REST / WebSocket |
| **Agent 层**      | 自然语言理解、任务编排、知识增强、报告生成 | DeerFlow 2.0 / qwen3.6 / RAG  |
| **前端**          | 对话交互 + 统计可视化                      | DeerFlow Web UI + Vue3        |

### 1.3 关键设计原则

- **Agent 不做业务计算**：衰耗计算、颜色判定、场景识别全部由后端完成，Agent 仅调用 API 获取结果并解读
- **Agent 专注智能交互**：意图理解、任务编排、知识检索、报告生成、趋势解读
- **插件化可扩展**：新 Tool / Sub-Agent 可通过标准接口热插拔
- **离线可用**：后端不可用时，Agent 仍可提供 RAG 知识问答

### 1.4 三轮澄清结论汇总

| 编号 | 结论                                                         |
| ---- | ------------------------------------------------------------ |
| Q1   | MCP 统一对接 API Gateway REST API `:8080`                    |
| Q2   | 颜色判定完全由后端实现，Agent 无需自行判定                   |
| Q3   | Agent 不做衰耗/颜色计算，移除沙箱脚本                        |
| Q4   | Vue3 直接订阅后端 WS `:8081`，无需独立推送服务               |
| Q5   | Port-2/Port-3 为后端实现细节，Agent 无需关心                 |
| Q6   | Agent 无需场景判断                                           |
| Q7   | 紧急告警光纤列表通过 `GET /api/v1/fibers/colored?color=RED` 获取 |
| Q8   | 按 DeerFlow 2.0 最新版本适配                                 |
| Q9   | 本地部署 qwen3.6，根据实际环境动态调整                       |
| Q10  | 知识库模板由开发方设计，初始内容由运维人员准备               |
| Q11  | 暂时单用户                                                   |
| Q12  | Python 自测客户端负责测试后端所有接口功能                    |
| Q13  | qwen3.6 根据实际环境动态调整降级策略                         |
| Q14  | 按 DeerFlow 主流方式设置 task tool                           |
| Q15  | 暂不考虑 API 认证（内网可信环境）                            |
| Q16  | fiber_id 为 int32，预计 10 万条，单次最大 100 条，FIFO 排队  |
| Q17  | 需持久化存储，支持对比分析                                   |
| Q18  | 支持导出 PDF/Excel/CSV，生成可下载文件                       |
| Q19  | 运维人员准备初始内容，提供管理界面，人工审核后入库           |
| Q20  | 订阅实时更新 + 定时轮询同步差异                              |
| Q21  | 测试后端所有接口，需模拟数据注入，生成报告，集成 CI/CD       |
| Q22  | 后续给出模拟界面评估                                         |
| Q24  | 日志输出到文件，需要 Prometheus + Grafana 监控               |
| Q25  | 后端不可用时需友好提示 + 离线模式 + 通知管理员               |
| Q26  | 需要插件化扩展架构                                           |
| Q27  | 默认最佳实践：Ubuntu 22.04 / Docker Compose / GPU 推理       |
| Q28  | 对比分析：同一光纤不同时间点 + 同网元对横向对比，后端提供历史数据 |
| Q29  | 轮询间隔 10s，增量更新，重连后补拉                           |
| Q30  | PDF + Excel + CSV，Python 生成，临时目录 + 下载链接，24h 清理 |
| Q31  | GitLab CI，每日定时 + 手动触发，失败阻断部署                 |
| Q32  | 邮件 + 企业微信，分级通知                                    |
| Q33  | 独立管理页面，上传→审核→入库，权限控制，支持删除/替换        |
| Q34  | 指定目录自动发现，支持热加载，提供插件 SDK 文档              |

------

## 2. 系统架构

### 2.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户交互层                                      │
│                                                                          │
│  ┌──────────────────────────┐  ┌──────────────────────────────────────┐  │
│  │  DeerFlow Web UI (:3000) │  │  Vue3 统计面板 (:5173)               │  │
│  │  · 对话/思考/工具/流式   │  │  · WS 订阅 :8081 (实时)             │  │
│  │  · 会话管理/历史         │  │  · REST 轮询 :8080 (10s 同步差异)   │  │
│  │  · 报告导出/下载         │  │  · 趋势图/统计仪表盘                │  │
│  │  · 知识库管理入口        │  │  · 颜色变化事件流                   │  │
│  └────────────┬─────────────┘  └──────────────────┬───────────────────┘  │
│               │ HTTP/WS :8000                     │ WS :8081 / REST :8080│
└───────────────┼───────────────────────────────────┼──────────────────────┘
                ▼                                   │
┌───────────────────────────────────────────────┐   │
│          DeerFlow 2.0 Agent 层                 │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  Lead Agent (qwen3.6)                   │  │   │
│  │  · 意图识别 / 任务分解 / 结果汇总       │  │   │
│  │  · task tool 派遣 Sub-Agent             │  │   │
│  └────────────────┬────────────────────────┘  │   │
│                   │ task tool                  │   │
│  ┌────────────────┼────────────────────────┐  │   │
│  │  Sub-Agents (并行, max=5, FIFO)         │  │   │
│  │  ├─ topology-analyst                    │  │   │
│  │  ├─ data-collector                      │  │   │
│  │  ├─ analysis-expert                     │  │   │
│  │  ├─ report-generator                    │  │   │
│  │  └─ rag-retriever                       │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  4 Middleware                            │  │   │
│  │  · ModelDegradationMW (模型降级)         │  │   │
│  │  · FiberDomainValidationMW (领域校验)    │  │   │
│  │  · RAGInjectionMW (知识注入)             │  │   │
│  │  · AuditLogMW (操作审计)                 │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  5 Markdown Skills                       │  │   │
│  │  · fiber_spanloss_analysis               │  │   │
│  │  · fiber_color_diagnosis                 │  │   │
│  │  · batch_fiber_analysis                  │  │   │
│  │  · fiber_trend_analysis                  │  │   │
│  │  · ne_health_check                       │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  RAG 引擎                                │  │   │
│  │  · ChromaDB + BGE-large-zh-v1.5         │  │   │
│  │  · BM25 + Reranker (bge-reranker-v2-m3) │  │   │
│  │  · 6 类知识库                            │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  Memory 系统                             │  │   │
│  │  · 短期: 50 条消息 (SQLite)              │  │   │
│  │  · 长期: 分析结果持久化 (SQLite)         │  │   │
│  │  · 对比分析: 时间序列存储                │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  MCP Connector → REST API :8080          │  │   │
│  │  · 14 个 Tool 函数                       │  │   │
│  │  · 重试(≤2次) / 超时(5s) / 错误处理     │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  导出引擎                                │  │   │
│  │  · PDF (reportlab) / Excel (openpyxl)    │  │   │
│  │  · CSV / 临时目录 + 下载链接 / 24h清理  │  │   │
│  └─────────────────────────────────────────┘  │   │
│                                               │   │
│  ┌─────────────────────────────────────────┐  │   │
│  │  插件化框架                              │  │   │
│  │  · 目录自动发现 / 热加载                 │  │   │
│  │  · 插件 SDK / 接口规范                   │  │   │
│  └─────────────────────────────────────────┘  │   │
└───────────────────────┬───────────────────────┘   │
                        │ HTTP REST (MCP)           │
                        ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                后端 C++ 微服务集群 (API Gateway :8080)                    │
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ BoardSvc │ │ TopoSvc  │ │ PerfSvc  │ │ AlarmSvc │ │FiberMaintSvc │  │
│  │ 单盘管理 │ │ 拓扑管理 │ │ 性能采集 │ │ 告警管理 │ │ 光纤维护     │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │ · 衰耗计算   │  │
│                                                       │ · 颜色判定   │  │
│  WebSocket :8081                                      │ · 场景识别   │  │
│  · alarm channel                                      │ · 统计趋势   │  │
│  · fiber_color channel                                │ · 历史数据   │  │
│  · fiber_stats channel                                └──────────────┘  │
│                                                                          │
│  内部通信: gRPC (微服务间)                                               │
│  数据存储: PostgreSQL / Redis / InfluxDB (时序)                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户自然语言输入
    │
    ▼
Lead Agent 意图识别
    │
    ├──→ [RAGInjectionMW] 关键词触发 → 知识注入
    │
    ├──→ task(topology-analyst) → MCP → GET /topology/fibers/{id}
    ├──→ task(data-collector)   → MCP → GET /fibers/{id}/performance
    │                                  GET /fibers/{id}/spanloss
    │                                  GET /alarms/current
    ├──→ task(analysis-expert)  → MCP → GET /fibers/colored
    │                                  GET /fibers/stats/trend
    │                                  + 长期记忆(历史对比)
    ├──→ task(report-generator) → RAG → 知识检索 + 报告生成
    │                                  + 导出引擎(PDF/Excel/CSV)
    └──→ task(rag-retriever)    → ChromaDB → 混合检索 + Rerank
    │
    ▼
Lead Agent 汇总 → 流式输出 → 用户
    │
    └──→ [AuditLogMW] 全链路审计日志 → 文件
```

------

## 3. Agent 层设计

### 3.1 Lead Agent

| 属性     | 值                                                     |
| -------- | ------------------------------------------------------ |
| 模型     | qwen3.6（动态调整）                                    |
| 最大迭代 | 10 轮                                                  |
| 核心能力 | 意图识别、任务分解、task tool 派遣、结果汇总、异常兜底 |
| 离线能力 | 后端不可用时，仅 RAG 知识问答 + 友好提示               |

**System Prompt 核心要素：**

```
你是光纤维护服务系统的智能分析助手。

【核心职责】
1. 理解用户的光纤分析需求（单条分析/批量分析/趋势查询/巡检/知识问答）
2. 分解任务，通过 task tool 派遣合适的子智能体执行
3. 汇总子智能体结果，生成结构化最终回复
4. 支持多轮对话、上下文引用、对比分析

【可用子智能体】
- topology-analyst: 查询光纤连接、单盘、网元信息
- data-collector: 获取性能、告警、统计、趋势数据
- analysis-expert: 解读衰耗/颜色结果、异常检测、趋势分析、对比分析
- report-generator: 生成结构化报告、维护建议、文件导出
- rag-retriever: 检索光纤领域知识库

【重要约束】
- 衰耗计算和颜色判定由后端 C++ 服务完成，你只需调用 API 获取结果并解读
- 操作对象仅限网元间连纤（src_ne_id ≠ dst_ne_id）
- 批量分析时并行派遣（最大 5 并发），FIFO 排队，单条失败不影响其他
- 单次批量查询最大 100 条
- 支持对比分析：同一光纤不同时间点 / 同网元对横向对比

【离线模式】
- 后端不可用时：提供 RAG 知识问答 + "后端服务暂时不可用" 友好提示
- 不编造数据，明确告知用户数据来源受限
```

### 3.2 Sub-Agent 定义

#### 3.2.1 topology-analyst

| 属性  | 值                                                           |
| ----- | ------------------------------------------------------------ |
| 模型  | qwen3.6（fast 模式）                                         |
| Tools | `fiber_connection_query`, `batch_fiber_connection_query`, `board_query`, `ne_query` |
| 职责  | 查询连纤连接信息、单盘信息、网元信息                         |
| 约束  | 不做场景判定、不做颜色计算                                   |

#### 3.2.2 data-collector

| 属性  | 值                                                           |
| ----- | ------------------------------------------------------------ |
| 模型  | qwen3.6（fast 模式）                                         |
| Tools | `fiber_performance_query`, `fiber_spanloss_query`, `alarm_query`, `colored_fibers_query`, `all_colored_fibers_query`, `fiber_stats_query`, `fiber_trend_query` |
| 职责  | 采集光纤性能、衰耗、告警、统计、趋势数据                     |
| 约束  | 仅采集，不做分析判断                                         |

#### 3.2.3 analysis-expert

| 属性  | 值                                                           |
| ----- | ------------------------------------------------------------ |
| 模型  | qwen3.6（primary 模式）                                      |
| Tools | `fiber_spanloss_query`, `colored_fibers_query`, `fiber_trend_query`, `memory_query`(长期记忆) |
| 职责  | 解读后端计算结果、异常检测、趋势分析、**对比分析**           |
| 约束  | 不做沙箱计算，仅解读 API 返回值                              |

**对比分析能力：**

- 纵向对比：同一光纤 F1001 今天 vs 昨天 vs 上周的衰耗变化
- 横向对比：同一网元对 NE101↔NE205 下多条连纤的性能对比
- 数据来源：后端历史数据 API + Agent 长期记忆

#### 3.2.4 report-generator

| 属性  | 值                                                           |
| ----- | ------------------------------------------------------------ |
| 模型  | qwen3.6（primary 模式）                                      |
| Tools | `rag_query`, `read_file`, `export_pdf`, `export_excel`, `export_csv` |
| 职责  | 生成结构化报告、维护建议、**文件导出**                       |
| 输出  | Markdown（对话内）+ PDF/Excel/CSV（可下载文件）              |

#### 3.2.5 rag-retriever

| 属性     | 值                                                           |
| -------- | ------------------------------------------------------------ |
| 模型     | qwen3.6（fast 模式）                                         |
| Tools    | `vector_search`, `bm25_search`, `reranker`, `knowledge_upload` |
| 职责     | 混合检索 + Reranker，返回 Top-K 知识片段                     |
| 检索策略 | Vector(0.6) + BM25(0.4) → Rerank → Top-3                     |

### 3.3 并发控制

| 参数               | 值                                        |
| ------------------ | ----------------------------------------- |
| 最大并发 Sub-Agent | 5                                         |
| 排队策略           | FIFO                                      |
| 单条任务超时       | 15s                                       |
| 批量任务总超时     | 30s                                       |
| 单次批量最大条数   | 100                                       |
| 失败策略           | 单条失败不影响其他，最终汇总成功/失败统计 |

------

## 4. Tools 定义

### 4.1 Tools 总览（14 个）

| #    | Tool 名称                                    | 所属 Agent                       | 后端 API                                           | 方法 |
| ---- | -------------------------------------------- | -------------------------------- | -------------------------------------------------- | ---- |
| 1    | `fiber_connection_query`                     | topology-analyst                 | `/api/v1/topology/fibers/{fiber_id}`               | GET  |
| 2    | `batch_fiber_connection_query`               | topology-analyst                 | `/api/v1/topology/fibers/batch`                    | POST |
| 3    | `board_query`                                | topology-analyst                 | `/api/v1/boards/{board_id}`                        | GET  |
| 4    | `ne_query`                                   | topology-analyst                 | `/api/v1/boards/{board_id}` (含 ne_id)             | GET  |
| 5    | `fiber_performance_query`                    | data-collector                   | `/api/v1/fibers/{fiber_id}/performance`            | GET  |
| 6    | `fiber_spanloss_query`                       | data-collector / analysis-expert | `/api/v1/fibers/{fiber_id}/spanloss`               | GET  |
| 7    | `alarm_query`                                | data-collector                   | `/api/v1/alarms/current?board_id=&port_id=`        | GET  |
| 8    | `colored_fibers_query`                       | data-collector / analysis-expert | `/api/v1/fibers/colored?color=RED|YELLOW`          | GET  |
| 9    | `all_colored_fibers_query`                   | data-collector                   | `/api/v1/fibers/colored/all`                       | GET  |
| 10   | `fiber_stats_query`                          | data-collector                   | `/api/v1/fibers/stats/realtime`                    | GET  |
| 11   | `fiber_trend_query`                          | data-collector / analysis-expert | `/api/v1/fibers/stats/trend?start_time=&end_time=` | GET  |
| 12   | `rag_query`                                  | report-generator / rag-retriever | ChromaDB 本地                                      | —    |
| 13   | `vector_search` / `bm25_search` / `reranker` | rag-retriever                    | ChromaDB + BM25                                    | —    |
| 14   | `knowledge_upload`                           | rag-retriever                    | ChromaDB 写入                                      | —    |

### 4.2 导出 Tools（3 个，report-generator 专用）

| #    | Tool 名称      | 功能            | 实现      |
| ---- | -------------- | --------------- | --------- |
| 15   | `export_pdf`   | 生成 PDF 报告   | reportlab |
| 16   | `export_excel` | 生成 Excel 报告 | openpyxl  |
| 17   | `export_csv`   | 生成 CSV 数据   | csv 模块  |

### 4.3 记忆 Tools（2 个，analysis-expert 专用）

| #    | Tool 名称      | 功能                             |
| ---- | -------------- | -------------------------------- |
| 18   | `memory_save`  | 持久化保存分析结果（含时间戳）   |
| 19   | `memory_query` | 查询历史分析结果（用于对比分析） |

### 4.4 Tool 参数规范

#### fiber_connection_query

```
输入:
  fiber_id: int32  # 光纤连纤 ID

输出:
  fiber_id: int32
  src_board_id: int32
  src_port_id: int32
  src_ne_id: int32
  dst_board_id: int32
  dst_port_id: int32
  dst_ne_id: int32
  created_at: string (ISO 8601)
```

#### fiber_performance_query

```
输入:
  fiber_id: int32

输出:
  fiber_id: int32
  src_oop: float (dBm)    # 源端输出光功率
  dst_iop: float (dBm)    # 宿端输入光功率
  timestamp: string (ISO 8601)
```

#### fiber_spanloss_query

```
输入:
  fiber_id: int32

输出:
  fiber_id: int32
  spanloss: float (dB)    # 后端计算的衰耗值
  timestamp: string (ISO 8601)
```

#### colored_fibers_query

```
输入:
  color: string  # "RED" | "YELLOW"

输出:
  fibers: [
    {
      fiber: { fiber_id, src_ne_id, dst_ne_id, ... },
      color: "RED" | "YELLOW",
      scene_type: int,       # 场景类型（后端判定）
      scenario_case: string  # 情况分类（后端判定）
    }
  ]
  total: int
```

#### fiber_trend_query

```
输入:
  start_time: string (ISO 8601)
  end_time: string (ISO 8601)

输出:
  data_points: [
    {
      timestamp: string,
      red_count: int,
      yellow_count: int,
      total_colored: int
    }
  ]
  granularity: "5min"
```

#### batch_fiber_connection_query

```
输入:
  fiber_ids: [int32]  # 最大 100 条

输出:
  fibers: [ FiberInfo ]
  not_found: [int32]  # 未找到的 ID 列表
  total: int
```

### 4.5 MCP 连接器规范

| 参数     | 值                                               |
| -------- | ------------------------------------------------ |
| 基础 URL | `http://localhost:8080`                          |
| 单次超时 | 5s                                               |
| 最大重试 | 2 次                                             |
| 批量超时 | 5s                                               |
| 认证     | 无（内网可信）                                   |
| 错误处理 | 404→NOT_FOUND / 5xx→重试 / 连接失败→不重试       |
| 审计     | 每次调用记录 method/path/status/elapsed/trace_id |

------

## 5. Middleware 设计

### 5.1 ModelDegradationMiddleware

| 属性     | 值                                            |
| -------- | --------------------------------------------- |
| 触发点   | `before_model` / `after_model` / `on_timeout` |
| 降级策略 | primary → fallback → fast → error（动态调整） |
| 熔断器   | 连续 3 次失败触发，60s 后半开恢复             |
| 模型     | qwen3.6（根据实际环境动态调整参数/量化级别）  |

**降级逻辑：**

```
正常: qwen3.6 (temperature=0.3, max_tokens=4096)
  ↓ 连续3次超时/失败
降级1: qwen3.6 (temperature=0.5, max_tokens=2048, 简化prompt)
  ↓ 连续3次超时/失败
降级2: qwen3.6 (temperature=0.1, max_tokens=1024, 极简prompt)
  ↓ 连续3次超时/失败
熔断: 返回 "服务暂时不可用" + 触发管理员通知
  ↓ 60s 后
半开: 尝试恢复 primary
```

### 5.2 FiberDomainValidationMiddleware

| 属性     | 值                                       |
| -------- | ---------------------------------------- |
| 触发点   | `after_tool`                             |
| 校验内容 | 网元间连纤验证 / OOP/IOP 范围 / 衰耗范围 |

**校验规则：**

| 校验项     | 正常范围              | 异常处理               |
| ---------- | --------------------- | ---------------------- |
| 网元间连纤 | src_ne_id ≠ dst_ne_id | 警告：仅处理网元间连纤 |
| OOP        | -30 ~ +10 dBm         | 标记异常               |
| IOP        | -40 ~ +5 dBm          | 标记异常               |
| 衰耗       | 0 ~ 30 dB             | > 30dB 标记异常偏高    |

### 5.3 RAGInjectionMiddleware

| 属性     | 值                                             |
| -------- | ---------------------------------------------- |
| 触发点   | `before_model`                                 |
| 触发方式 | 关键词匹配 → 自动混合检索 → 注入 system prompt |
| 注入上限 | Top-3 知识片段，总计 ≤ 2000 tokens             |

**关键词映射表：**

| 关键词                       | 触发 Skill              | 检索 Collection                        |
| ---------------------------- | ----------------------- | -------------------------------------- |
| 衰耗/光功率/spanloss/OOP/IOP | fiber_spanloss_analysis | threshold_standard                     |
| 告警/颜色/红色/黄色/中断     | fiber_color_diagnosis   | alarm_guide                            |
| 批量/所有/全部               | batch_fiber_analysis    | maintenance_guide                      |
| 趋势/变化/统计/历史          | fiber_trend_analysis    | fault_cases                            |
| 巡检/健康/网元               | ne_health_check         | maintenance_guide                      |
| 维护/阈值/规范               | —                       | maintenance_guide + threshold_standard |

### 5.4 AuditLogMiddleware

| 属性     | 值                                                           |
| -------- | ------------------------------------------------------------ |
| 触发点   | `before_tool` / `after_tool`                                 |
| 输出     | 文件（JSON Lines 格式）                                      |
| 记录内容 | trace_id / tool_name / args / status / elapsed_ms / timestamp |
| 关联     | 通过 trace_id 与后端 C++ 日志关联                            |

**日志格式：**

```json
{
  "event": "tool_call_end",
  "trace_id": "abc-123-def",
  "tool": "fiber_spanloss_query",
  "args": {"fiber_id": 1001},
  "status": 200,
  "elapsed_ms": 45.2,
  "timestamp": "2026-07-21T15:30:00+08:00"
}
```

------

## 6. Markdown Skills

### 6.1 Skills 总览

| #    | Skill 文件                   | 触发场景        | 核心流程                                 |
| ---- | ---------------------------- | --------------- | ---------------------------------------- |
| 1    | `fiber_spanloss_analysis.md` | 衰耗/光功率查询 | 获取性能→获取衰耗→阈值判断→结论→建议     |
| 2    | `fiber_color_diagnosis.md`   | 颜色/告警诊断   | 获取颜色→获取告警→获取性能→综合诊断→建议 |
| 3    | `batch_fiber_analysis.md`    | 批量/所有/全部  | 获取列表→并行分析→汇总→排序→共性问题     |
| 4    | `fiber_trend_analysis.md`    | 趋势/变化/统计  | 获取趋势→获取统计→异常检测→预测→建议     |
| 5    | `ne_health_check.md`         | 巡检/健康/网元  | 获取关联→逐条检查→健康评分→问题清单→建议 |

### 6.2 Skill 文件格式规范

```markdown
---
name: <skill_name>
description: <一句话描述>
version: "1.0"
triggers:
  - <关键词1>
  - <关键词2>
tools_required:
  - <tool_name_1>
  - <tool_name_2>
output_format: markdown
---

# <Skill 标题>

## 触发条件
<何时激活此 Skill>

## 执行步骤
### Step 1: ...
### Step 2: ...

## 判定标准
<阈值/规则表>

## 输出模板
<Markdown 模板>

## 异常处理
<数据缺失/超时/错误的处理方式>
```

### 6.3 各 Skill 详细内容

#### 6.3.1 fiber_spanloss_analysis.md

```markdown
---
name: fiber_spanloss_analysis
description: 光纤衰耗分析完整流程
version: "1.0"
triggers: [衰耗, 光功率, spanloss, OOP, IOP, dB]
tools_required: [fiber_performance_query, fiber_spanloss_query, rag_query]
output_format: markdown
---

# 光纤衰耗分析技能

## 触发条件
用户询问光纤衰耗、光功率、OOP/IOP 相关问题

## 执行步骤

### Step 1: 获取光纤性能数据
- 调用 fiber_performance_query(fiber_id) → OOP/IOP
- 调用 fiber_spanloss_query(fiber_id) → 后端计算的衰耗值

### Step 2: 阈值判断（参考知识库）
| 光纤类型 | 波长 | 正常 | 告警 | 紧急 |
|----------|------|------|------|------|
| G.652 单模 | 1310nm | ≤0.4 dB/km | >0.5 | >0.8 |
| G.652 单模 | 1550nm | ≤0.3 dB/km | >0.4 | >0.6 |
| G.651 多模 | 850nm | ≤3.5 dB/km | >4.0 | >5.0 |

### Step 3: 状态判定
- 🟢 正常: 衰耗在正常范围内
- 🟡 关注: 超正常范围但未达告警阈值
- 🔴 异常: 超告警阈值

### Step 4: 生成维护建议
- 检索 RAG 知识库获取对应维护规范
- 引用具体条款编号

## 输出模板

## 光纤 F{fiber_id} 衰耗分析

| 指标 | 值 | 状态 |
|------|-----|------|
| 源端 OOP | {oop} dBm | {status} |
| 宿端 IOP | {iop} dBm | {status} |
| 衰耗值 | {spanloss} dB | {status} |
| 阈值 | {threshold} dB | — |

**结论**: {conclusion}
**建议**: {suggestion}
**参考**: {rag_reference}

## 异常处理
- 性能数据缺失 → 提示"暂无性能数据，请确认采集是否正常"
- 衰耗查询超时 → 重试 1 次，仍失败则提示用户
- fiber_id 不存在 → 提示"未找到该光纤，请确认 ID"
```

#### 6.3.2 fiber_color_diagnosis.md

```markdown
---
name: fiber_color_diagnosis
description: 光纤颜色诊断与告警处理
version: "1.0"
triggers: [颜色, 红色, 黄色, 告警, 中断, 紧急]
tools_required: [colored_fibers_query, alarm_query, fiber_performance_query, fiber_spanloss_query]
output_format: markdown
---

# 光纤颜色诊断技能

## 颜色含义
| 颜色 | 含义 | 紧急程度 | 响应时间 |
|------|------|----------|----------|
| 🟢 绿色 | 正常 | — | — |
| 🟡 黄色 | 次要告警/性能劣化 | 关注 | ≤4h |
| 🔴 红色 | 紧急告警/链路中断 | 立即 | ≤15min |

## 执行步骤

### Step 1: 获取颜色状态
- colored_fibers_query(color="RED") → 红色连纤列表
- colored_fibers_query(color="YELLOW") → 黄色连纤列表
- 后端返回 scene_type + scenario_case（Agent 仅展示，不做判定）

### Step 2: 获取关联告警
- 根据连纤的 board_id + port_id 查询 alarm_query

### Step 3: 获取性能数据
- fiber_performance_query + fiber_spanloss_query 确认当前状态

### Step 4: 综合诊断
- 红色: 通常为 CRITICAL 告警触发
- 黄色: 通常为 MINOR 告警或性能劣化
- 同网元对多条红色 → 疑似光缆故障（参考案例库）

### Step 5: 处理建议（按优先级）
- P0: 红色+紧急告警 → 15min 内响应
- P1: 红色+无告警 → 30min 内响应
- P2: 黄色+次要告警 → 4h 内处理
- P3: 黄色+趋势劣化 → 下次巡检

## 输出模板

## 光纤颜色诊断报告

### 当前状态
- 🔴 红色: {red_count} 条
- 🟡 黄色: {yellow_count} 条

### 详细分析
| 光纤 | 颜色 | 网元对 | 场景 | 情况 | 告警 | 优先级 |
|------|------|--------|------|------|------|--------|

### 处理建议
{按 P0→P3 排序}

### 参考
{RAG 知识引用}
```

#### 6.3.3 batch_fiber_analysis.md

```markdown
---
name: batch_fiber_analysis
description: 批量光纤分析策略
version: "1.0"
triggers: [批量, 所有, 全部, 紧急告警光纤]
tools_required: [colored_fibers_query, all_colored_fibers_query, fiber_spanloss_query, fiber_performance_query]
output_format: markdown
---

# 批量光纤分析技能

## 触发条件
用户要求分析"所有告警光纤"、"批量分析"、"全部红色连纤"

## 执行策略

### Step 1: 获取目标列表
- 紧急: colored_fibers_query(color="RED")
- 全部: all_colored_fibers_query()
- 上限: 100 条/次，超出分批

### Step 2: 并行分析
- Lead Agent 通过 task tool 并行派遣（max 5 并发）
- FIFO 排队
- 每条光纤独立分析，失败不影响其他
- 单条超时 15s

### Step 3: 汇总报告
- 成功/失败统计
- 按严重程度排序（红→黄→绿）
- 共性问题归纳
- 优先处理建议

## 输出模板

## 批量分析报告

### 概览
- 分析总数: {total} | 成功: {success} | 失败: {failed}
- 🔴 {red} | 🟡 {yellow} | 🟢 {green}

### 紧急处理清单
| 优先级 | 光纤 | 问题 | 建议 |
|--------|------|------|------|

### 共性问题
{归纳}

### 失败条目
| 光纤 | 原因 |
|------|------|
```

#### 6.3.4 fiber_trend_analysis.md

```markdown
---
name: fiber_trend_analysis
description: 光纤趋势分析与异常检测
version: "1.0"
triggers: [趋势, 变化, 统计, 历史, 走势, 对比]
tools_required: [fiber_trend_query, fiber_stats_query, memory_query]
output_format: markdown
---

# 光纤趋势分析技能

## 触发条件
用户询问趋势、变化、统计、历史对比

## 执行步骤

### Step 1: 获取趋势数据
- fiber_trend_query(start_time, end_time)
- 支持: 1h / 6h / 24h / 7d / 30d
- 粒度: 5 分钟

### Step 2: 获取实时统计
- fiber_stats_query() → 当前红/黄数量

### Step 3: 对比分析（如需要）
- 纵向: memory_query(fiber_id, time_range) → 历史分析结果
- 横向: 同网元对下多条连纤对比

### Step 4: 异常检测
- 突增: 短时间内红色数量急剧增加
- 趋势预警: 黄色持续增加
- 周期: 是否存在周期性波动

### Step 5: 生成报告 + 预测建议

## 输出模板

## 光纤趋势分析 ({time_range})

### 当前状态
- 🔴 {red} | 🟡 {yellow} | 总计 {total}

### 趋势概要
- 红色峰值: {max_red} @ {time}
- 变化趋势: {上升/下降/平稳}

### 对比分析（如有）
| 时间 | 衰耗 | 变化 |
|------|------|------|

### 异常事件
| 时间 | 事件 | 影响 |
|------|------|------|

### 建议
{基于趋势的维护建议}
```

#### 6.3.5 ne_health_check.md

```markdown
---
name: ne_health_check
description: 网元级光纤健康巡检
version: "1.0"
triggers: [巡检, 健康, 网元, 检查]
tools_required: [board_query, fiber_connection_query, fiber_performance_query, fiber_spanloss_query, alarm_query, colored_fibers_query]
output_format: markdown
---

# 网元健康巡检技能

## 执行步骤

### Step 1: 获取网元关联连纤
- board_query → 网元下所有单盘
- fiber_connection_query → 关联连纤（仅网元间）

### Step 2: 逐条检查
- 性能: OOP/IOP 正常？
- 衰耗: 在阈值内？
- 告警: 有活跃告警？
- 颜色: 绿色？

### Step 3: 健康评分
- 100分: 全绿 + 无告警
- 60-90: 有黄色
- 0-60: 有红色

### Step 4: 巡检报告

## 输出模板

## 网元 NE{ne_id} 健康巡检报告

### 健康评分: {score}/100 {emoji}

### 概览
- 关联连纤: {total} | 🟢{green} 🟡{yellow} 🔴{red}
- 活跃告警: {alarm_count}

### 问题清单
| 光纤 | 问题 | 严重度 | 建议 |
|------|------|--------|------|

### 维护建议
{按优先级}

### 下次巡检建议: {date}
```

------

## 7. RAG 知识库

### 7.1 技术配置

| 参数           | 值                             |
| -------------- | ------------------------------ |
| 向量数据库     | ChromaDB                       |
| Embedding 模型 | BAAI/bge-large-zh-v1.5         |
| Reranker 模型  | BAAI/bge-reranker-v2-m3        |
| 分块大小       | 512 tokens                     |
| 分块重叠       | 50 tokens                      |
| 分块器         | RecursiveCharacterTextSplitter |
| Vector Top-K   | 10                             |
| BM25 Top-K     | 10                             |
| Reranker Top-K | 3（最终返回）                  |
| 混合权重       | Vector 0.6 + BM25 0.4          |

### 7.2 知识库分类（6 类）

| #    | Collection           | 目录            | 内容                         | 初始文档数 |
| ---- | -------------------- | --------------- | ---------------------------- | ---------- |
| 1    | `device_manual`      | 01_设备技术手册 | 有源盘/无源盘规格、端口约束  | 3          |
| 2    | `maintenance_guide`  | 02_维护操作规范 | 巡检规范、抢修流程、安全规范 | 3          |
| 3    | `alarm_guide`        | 03_告警处理指南 | 告警级别、处理流程、升级规则 | 3          |
| 4    | `fault_cases`        | 04_历史故障案例 | 典型故障案例（持续积累）     | 3          |
| 5    | `threshold_standard` | 05_衰耗阈值标准 | 阈值表、光功率范围、判定规则 | 2          |
| 6    | `ne_config`          | 06_网元配置规范 | 组网规则、配置约束           | 2          |

### 7.3 知识库目录结构

```
knowledge_base/
├── 01_设备技术手册/
│   ├── 有源盘技术规格.md
│   ├── 无源盘技术规格.md
│   └── 端口规格与约束.md
├── 02_维护操作规范/
│   ├── 日常巡检规范.md
│   ├── 故障抢修流程.md
│   └── 维护安全规范.md
├── 03_告警处理指南/
│   ├── 告警级别定义.md
│   ├── 紧急告警处理流程.md
│   └── 告警升级规则.md
├── 04_历史故障案例/
│   ├── 案例001_光纤中断.md
│   ├── 案例002_衰耗异常.md
│   └── 案例003_间歇性告警.md
├── 05_衰耗阈值标准/
│   ├── 光纤衰耗阈值表.md
│   └── 光功率正常范围.md
└── 06_网元配置规范/
    ├── 组网规则.md
    └── 配置约束.md
```

### 7.4 初始知识库内容

#### 7.4.1 光纤衰耗阈值表

| 光纤类型   | 波长   | 衰减系数    | 正常范围 | 告警阈值 | 紧急阈值 |
| ---------- | ------ | ----------- | -------- | -------- | -------- |
| G.652 单模 | 1310nm | ≤0.35 dB/km | 0~0.4    | >0.5     | >0.8     |
| G.652 单模 | 1550nm | ≤0.22 dB/km | 0~0.3    | >0.4     | >0.6     |
| G.655 单模 | 1550nm | ≤0.25 dB/km | 0~0.3    | >0.4     | >0.6     |
| G.651 多模 | 850nm  | ≤3.5 dB/km  | 0~3.5    | >4.0     | >5.0     |
| G.651 多模 | 1300nm | ≤1.5 dB/km  | 0~1.5    | >2.0     | >3.0     |

**链路总衰耗判定：**

| 链路长度 | 正常   | 关注  | 告警 |
| -------- | ------ | ----- | ---- |
| ≤10km    | ≤4 dB  | 4~6   | >6   |
| 10~40km  | ≤12 dB | 12~16 | >16  |
| 40~80km  | ≤22 dB | 22~28 | >28  |
| >80km    | ≤30 dB | 30~35 | >35  |

**光功率正常范围：**

| 参数         | 正常         | 异常          |
| ------------ | ------------ | ------------- |
| OOP          | -10 ~ +3 dBm | < -15 或 > +5 |
| IOP          | -25 ~ -5 dBm | < -30 或 > 0  |
| OOP-IOP 差值 | 0 ~ 25 dB    | > 30          |

#### 7.4.2 告警级别定义

| 级别          | 代码 | 含义              | 响应时间 |
| ------------- | ---- | ----------------- | -------- |
| 紧急 CRITICAL | 1    | 业务中断/严重故障 | ≤15min   |
| 次要 MINOR    | 2    | 性能劣化/潜在风险 | ≤4h      |

**处理优先级：**

- P0: 红色 + 紧急告警 → 15min
- P1: 红色 + 无告警 → 30min
- P2: 黄色 + 次要告警 → 4h
- P3: 黄色 + 趋势劣化 → 下次巡检

**升级规则：**

- 次要 > 24h 未处理 → 升级紧急
- 同一光纤 24h 内 ≥ 3 次告警 → 升级紧急
- 同网元对多条连纤同时告警 → 升级紧急

#### 7.4.3 日常巡检规范

| 类型 | 周期 | 内容                    |
| ---- | ---- | ----------------------- |
| 日常 | 每日 | 红/黄统计，紧急告警处理 |
| 周期 | 每周 | 全量性能检查，趋势分析  |
| 深度 | 每月 | 历史分析，阈值评估      |
| 专项 | 按需 | 施工前后、恶劣天气后    |

#### 7.4.4 历史故障案例（模板）

```markdown
# 故障案例 {编号}: {标题}

## 基本信息
- 时间:
- 影响: {网元对} 之间 {N} 条连纤
- 持续:
- 级别: P{0-3}

## 现象描述
{告警/颜色/性能变化}

## 根因分析
{物理/设备/配置/外部}

## 处理过程
1. {时间} {动作}
2. ...

## 经验总结
{可复用的判断规则}

## 关联知识
{引用的规范/标准}
```

### 7.5 知识库更新流程

```
运维人员上传文档
    │
    ▼
管理界面 (/admin/knowledge)
    │
    ▼
待审核队列
    │
    ▼
管理员审核 (通过/驳回)
    │
    ├── 通过 → 分块 → 向量化 → 入库 ChromaDB → 可检索
    │
    └── 驳回 → 退回修改
```

------

## 8. 前端统计面板

### 8.1 架构

```
Vue3 统计面板 (:5173)
    │
    ├── WebSocket 订阅 (ws://backend:8081/ws/v1/events)
    │   ├── channel: fiber_stats  → 实时统计更新
    │   ├── channel: fiber_color  → 颜色变化事件
    │   └── channel: alarm        → 告警事件
    │
    ├── REST 轮询 (http://backend:8080, 间隔 10s)
    │   └── GET /api/v1/fibers/stats/realtime → 差异同步
    │
    └── REST 按需查询
        └── GET /api/v1/fibers/stats/trend → 趋势图数据
```

### 8.2 双模式数据同步策略

| 模式             | 机制          | 用途                       |
| ---------------- | ------------- | -------------------------- |
| **订阅（实时）** | WS :8081 推送 | 颜色变化、告警事件即时展示 |
| **轮询（同步）** | REST 10s 间隔 | 校准本地状态，补漏订阅丢失 |

**差异同步逻辑：**

- 轮询获取最新统计 → 与本地缓存对比
- 不一致 → **增量更新**（仅更新变化字段）
- WS 断线重连后 → **补拉**断线期间变更（通过 last_event_id）

### 8.3 面板组件

| 组件                | 功能                      |
| ------------------- | ------------------------- |
| `StatsOverview.vue` | 红/黄/绿数量仪表盘        |
| `TrendChart.vue`    | 时间序列趋势图（ECharts） |
| `RecentChanges.vue` | 最近颜色变化事件流        |
| `AlarmList.vue`     | 活跃告警列表              |
| `FiberDetail.vue`   | 单条光纤详情弹窗          |

### 8.4 WebSocket 心跳与重连

| 参数         | 值                                    |
| ------------ | ------------------------------------- |
| 心跳间隔     | 15s (ping/pong)                       |
| 断线重连     | 3s 后自动重连                         |
| 重连后补拉   | 通过 last_event_id 补拉缺失事件       |
| 最大重连次数 | 无限制（指数退避: 3s→6s→12s→30s max） |

------

## 9. 导出与报告

### 9.1 支持格式

| 格式         | 用途                   | 实现库                 |
| ------------ | ---------------------- | ---------------------- |
| **PDF**      | 正式报告（含图表）     | reportlab + matplotlib |
| **Excel**    | 数据表格（可二次编辑） | openpyxl               |
| **CSV**      | 原始数据导出           | csv 模块               |
| **Markdown** | 对话内展示             | 原生                   |

### 9.2 文件生成流程

```
用户: "导出批量分析报告为 PDF"
    │
    ▼
report-generator Sub-Agent
    │
    ├── 汇总分析数据
    ├── 调用 export_pdf(data, template)
    │   └── Python: reportlab 生成 PDF
    │       └── 存储: /tmp/fiber_reports/{trace_id}_{timestamp}.pdf
    │
    ▼
返回下载链接: http://deerflow:8000/api/v1/reports/download/{file_id}
    │
    ▼
用户点击下载
```

### 9.3 文件管理

| 参数         | 值                             |
| ------------ | ------------------------------ |
| 存储位置     | `/tmp/fiber_reports/`          |
| 命名规则     | `{trace_id}_{timestamp}.{ext}` |
| 保留时间     | 24 小时自动清理                |
| 清理机制     | 定时任务（每小时扫描过期文件） |
| 下载方式     | HTTP 下载链接                  |
| 文件大小限制 | 单文件 ≤ 50MB                  |

### 9.4 报告模板

**PDF 报告结构：**

```
1. 封面（标题、时间、生成者）
2. 概览（统计摘要）
3. 详细分析（逐条光纤）
4. 趋势图表（matplotlib 生成）
5. 处理建议
6. 参考知识（RAG 引用）
7. 附录（原始数据表）
```

------

## 10. 记忆系统

### 10.1 架构

| 层级         | 存储            | 容量      | 用途                                 |
| ------------ | --------------- | --------- | ------------------------------------ |
| **短期记忆** | SQLite (内存)   | 50 条消息 | 当前会话上下文                       |
| **长期记忆** | SQLite (持久化) | 无限制    | 分析结果持久化、对比分析             |
| **用户偏好** | SQLite          | —         | 用户习惯（如常用网元、报告格式偏好） |

### 10.2 长期记忆数据模型

```sql
CREATE TABLE analysis_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiber_id INTEGER NOT NULL,
    analysis_type TEXT NOT NULL,  -- 'spanloss' | 'color' | 'trend' | 'health'
    result_json TEXT NOT NULL,    -- 分析结果 JSON
    summary TEXT,                 -- 摘要
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trace_id TEXT
);

CREATE INDEX idx_fiber_time ON analysis_history(fiber_id, created_at);
CREATE INDEX idx_type_time ON analysis_history(analysis_type, created_at);
```

### 10.3 对比分析支持

**纵向对比（同一光纤不同时间）：**

```
用户: "F1001 今天和上周比有什么变化？"
    │
    ▼
analysis-expert:
    1. memory_query(fiber_id=1001, range="today") → 今天结果
    2. memory_query(fiber_id=1001, range="last_week") → 上周结果
    3. fiber_trend_query(7d) → 后端趋势数据
    4. 对比分析 → 输出变化报告
```

**横向对比（同网元对多条连纤）：**

```
用户: "NE101到NE205之间哪条光纤最差？"
    │
    ▼
analysis-expert:
    1. 获取 NE101↔NE205 所有连纤
    2. 逐条获取衰耗/性能
    3. 排序对比 → 输出最差光纤 + 原因
```

### 10.4 多轮对话上下文引用

支持模式：

- "那 F1002 呢？" → 从短期记忆获取上一轮意图（分析），替换 fiber_id
- "和上次比有什么变化？" → 从长期记忆获取上次分析结果
- "把刚才的结果导出" → 从短期记忆获取上一轮输出，调用导出引擎

------

## 11. Python 自测客户端

### 11.1 测试范围

覆盖后端**所有 REST API 接口**：

| 模块 | 接口                               | 测试内容                |
| ---- | ---------------------------------- | ----------------------- |
| 拓扑 | `GET /topology/fibers/{id}`        | 正常/不存在/参数错误    |
| 拓扑 | `POST /topology/fibers/batch`      | 正常/部分不存在/超100条 |
| 单盘 | `GET /boards/{id}`                 | 正常/不存在             |
| 单盘 | `POST /boards/batch`               | 正常/部分不存在         |
| 性能 | `GET /fibers/{id}/performance`     | 正常/无数据             |
| 衰耗 | `GET /fibers/{id}/spanloss`        | 正常/无数据             |
| 颜色 | `GET /fibers/colored?color=RED`    | 有数据/无数据           |
| 颜色 | `GET /fibers/colored?color=YELLOW` | 有数据/无数据           |
| 颜色 | `GET /fibers/colored/all`          | 有数据/无数据           |
| 统计 | `GET /fibers/stats/realtime`       | 正常                    |
| 趋势 | `GET /fibers/stats/trend`          | 正常/时间范围无效       |
| 告警 | `GET /alarms/current`              | 有告警/无告警           |
| WS   | `ws://:8081/ws/v1/events`          | 连接/订阅/心跳/消息接收 |

### 11.2 模拟数据注入

```python
# 测试前置: 注入测试数据
class TestDataInjector:
    """通过后端 API 注入测试数据"""
    
    async def inject_test_fibers(self, count=10):
        """创建测试连纤"""
        
    async def inject_test_alarms(self, fiber_ids, level="CRITICAL"):
        """注入测试告警"""
        
    async def inject_test_performance(self, fiber_id, oop, iop):
        """注入测试性能数据"""
        
    async def cleanup(self):
        """清理测试数据"""
```

### 11.3 颜色验证测试

```python
class ColorVerificationTest:
    """验证后端颜色判定逻辑"""
    
    async def test_red_on_critical_alarm(self):
        """紧急告警 → 红色"""
        
    async def test_yellow_on_minor_alarm(self):
        """次要告警 → 黄色"""
        
    async def test_green_on_no_alarm(self):
        """无告警 + 性能正常 → 绿色"""
        
    async def test_color_change_on_alarm_clear(self):
        """告警清除 → 颜色恢复"""
        
    async def test_batch_color_consistency(self):
        """批量查询颜色一致性"""
```

### 11.4 测试报告输出

```
test_reports/
├── report_20260721_153000.html    # HTML 可视化报告
├── report_20260721_153000.json    # JSON 结构化数据
└── report_20260721_153000.log     # 详细日志
```

**报告内容：**

- 测试总数 / 通过 / 失败 / 跳过
- 各接口响应时间统计
- 失败用例详情 + 错误信息
- 颜色验证结果矩阵
- 性能基准（P50/P95/P99）

### 11.5 CI/CD 集成

| 参数     | 值                                        |
| -------- | ----------------------------------------- |
| 平台     | GitLab CI                                 |
| 触发     | 每日定时 (02:00) + 手动触发 + MR 合并触发 |
| 阻断策略 | 测试失败 → **阻断部署**                   |
| 通知     | 失败 → 企业微信通知                       |
| 制品     | 测试报告归档 30 天                        |

------

## 12. 知识库管理界面

### 12.1 功能清单

| 功能       | 描述                               |
| ---------- | ---------------------------------- |
| 文档上传   | 支持 PDF/Word/Markdown/TXT         |
| 待审核列表 | 展示所有待审核文档                 |
| 审核操作   | 通过 / 驳回（附原因）              |
| 入库管理   | 查看已入库文档、分块数、向量化状态 |
| 删除/替换  | 删除旧版本、替换更新               |
| 检索测试   | 输入查询测试检索效果               |
| 权限控制   | 管理员（审核）/ 运维人员（上传）   |

### 12.2 审核流程

```
运维人员上传 → 状态: PENDING
    │
    ▼
管理员审核
    ├── 通过 → 分块 → 向量化 → 入库 → 状态: ACTIVE
    └── 驳回 → 状态: REJECTED (附原因)
    
管理员操作:
    ├── 删除 → 从 ChromaDB 移除向量 → 状态: DELETED
    └── 替换 → 旧版本 DELETED + 新版本 PENDING
```

### 12.3 访问路径

- 独立页面: `http://deerflow:3000/admin/knowledge`
- 权限: 需登录，角色区分（admin / operator）

------

## 13. 监控与日志

### 13.1 日志体系

| 日志类型       | 输出                                    | 格式       | 保留  |
| -------------- | --------------------------------------- | ---------- | ----- |
| Agent 审计日志 | 文件 `/var/log/fiber-agent/audit.jsonl` | JSON Lines | 90 天 |
| Agent 运行日志 | 文件 `/var/log/fiber-agent/app.log`     | 标准日志   | 30 天 |
| MCP 调用日志   | 文件 `/var/log/fiber-agent/mcp.jsonl`   | JSON Lines | 30 天 |
| 后端 C++ 日志  | 文件（后端管理）                        | —          | —     |
| **关联**       | 通过 `trace_id` 贯穿 Agent ↔ 后端       | —          | —     |

### 13.2 Prometheus + Grafana 监控

**Agent 层指标：**

| 指标                               | 类型      | 说明                       |
| ---------------------------------- | --------- | -------------------------- |
| `agent_request_duration_seconds`   | Histogram | 请求响应时间               |
| `agent_tool_call_total`            | Counter   | 工具调用次数（按 tool 分） |
| `agent_tool_call_errors_total`     | Counter   | 工具调用失败次数           |
| `agent_llm_tokens_total`           | Counter   | Token 消耗（input/output） |
| `agent_llm_latency_seconds`        | Histogram | LLM 推理延迟               |
| `agent_model_degradation_total`    | Counter   | 模型降级次数               |
| `agent_subagent_concurrent`        | Gauge     | 当前并发 Sub-Agent 数      |
| `agent_rag_query_duration_seconds` | Histogram | RAG 检索延迟               |

**后端层指标（通过 API Gateway 暴露）：**

| 指标                            | 说明                 |
| ------------------------------- | -------------------- |
| `http_request_duration_seconds` | API 响应时间         |
| `fiber_colored_total`           | 有颜色连纤数量       |
| `alarm_active_total`            | 活跃告警数量         |
| `ws_connections_active`         | WebSocket 活跃连接数 |

**Grafana 仪表盘：**

- Agent 性能概览（QPS / 延迟 / 错误率）
- LLM 推理监控（Token / 延迟 / 降级）
- 光纤状态大盘（红/黄/绿趋势）
- 告警统计（按级别/网元/时间）

------

## 14. 异常处理与容错

### 14.1 后端不可用

| 场景           | Agent 行为                                                   |
| -------------- | ------------------------------------------------------------ |
| 单次请求超时   | 重试 ≤ 2 次，仍失败返回错误信息                              |
| 后端完全不可用 | 进入**离线模式**：仅 RAG 知识问答                            |
| 离线模式提示   | "⚠️ 后端服务暂时不可用，当前仅提供知识库问答。实时数据暂不可获取。" |
| 恢复后         | 自动退出离线模式，恢复正常调用                               |

### 14.2 管理员通知

| 触发条件             | 级别 | 通知渠道        |
| -------------------- | ---- | --------------- |
| 后端连续不可用 > 60s | 严重 | 企业微信 + 邮件 |
| Agent 模型熔断       | 严重 | 企业微信 + 邮件 |
| 批量分析失败率 > 50% | 一般 | 邮件            |
| 单次请求超时 > 3 次  | 一般 | 邮件            |
| 磁盘空间 < 10%       | 一般 | 邮件            |

**通知分级：**

- **严重**（立即）: 企业微信实时推送 + 邮件
- **一般**（汇总）: 每 30 分钟汇总邮件

### 14.3 数据一致性

| 场景         | 处理                                 |
| ------------ | ------------------------------------ |
| 并发修改     | 后端保证（Agent 只读）               |
| 缓存不一致   | 轮询 10s 同步差异                    |
| WS 消息丢失  | 重连后通过 last_event_id 补拉        |
| 分析结果过期 | 长期记忆带时间戳，对比时标注数据时间 |

------

## 15. 插件化扩展架构

### 15.1 插件类型

| 类型                | 扩展方式                                  | 热加载   |
| ------------------- | ----------------------------------------- | -------- |
| **Tool 插件**       | 放入 `plugins/tools/` 目录，自动发现      | ✅        |
| **Sub-Agent 插件**  | 放入 `plugins/agents/` 目录 + config 声明 | ✅        |
| **Skill 插件**      | 放入 `skills/` 目录，自动加载             | ✅        |
| **Middleware 插件** | config.yaml 声明 + 代码注册               | ❌ 需重启 |

### 15.2 Tool 插件规范

```python
# plugins/tools/example_tool.py

from deerflow.plugin import ToolPlugin, tool

class ExamplePlugin(ToolPlugin):
    """插件元信息"""
    name = "example_tool"
    version = "1.0.0"
    description = "示例工具插件"
    author = "developer"
    
    @tool
    async def example_query(self, param: str) -> str:
        """工具描述（LLM 可见）
        
        Args:
            param: 参数说明
        """
        # 实现逻辑
        return "result"
```

### 15.3 Sub-Agent 插件规范

```python
# plugins/agents/example_agent.py

from deerflow.plugin import AgentPlugin

class ExampleAgentPlugin(AgentPlugin):
    name = "example-agent"
    description = "示例智能体"
    model = "fast"
    tools = ["example_query"]
    
    system_prompt = """你是..."""
```

### 15.4 插件 SDK 文档

提供 `docs/PLUGIN_SDK.md`，包含：

- 插件开发指南
- 接口规范
- 示例代码
- 测试方法
- 发布流程

------

## 16. 部署方案

### 16.1 环境要求

| 组件           | 要求                                          |
| -------------- | --------------------------------------------- |
| OS             | Ubuntu 22.04 LTS                              |
| GPU            | NVIDIA GPU（≥ 24GB VRAM，推荐 A100/RTX 4090） |
| CPU            | ≥ 8 核                                        |
| 内存           | ≥ 64GB                                        |
| 磁盘           | ≥ 500GB SSD                                   |
| Docker         | ≥ 24.0                                        |
| Docker Compose | ≥ 2.20                                        |
| NVIDIA Driver  | ≥ 535                                         |
| CUDA           | ≥ 12.0                                        |

### 16.2 Docker Compose 编排

```yaml
version: "3.9"

services:
  # ═══════════ LLM 推理 ═══════════
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped

  # ═══════════ DeerFlow Agent ═══════════
  deerflow:
    build:
      context: ./deer-flow
      dockerfile: Dockerfile
    ports:
      - "8000:8000"   # API
      - "3000:3000"   # Web UI
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./knowledge_base:/app/knowledge_base
      - ./skills:/app/skills
      - ./plugins:/app/plugins
      - agent_logs:/var/log/fiber-agent
      - report_tmp:/tmp/fiber_reports
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - FIBER_BACKEND_URL=http://fiber-backend:8080
      - FIBER_WS_URL=ws://fiber-backend:8081
      - CHROMADB_URL=http://chromadb:8000
    depends_on:
      - ollama
      - chromadb
    restart: unless-stopped

  # ═══════════ 向量数据库 ═══════════
  chromadb:
    image: chromadb/chroma:latest
    ports: ["8100:8000"]
    volumes:
      - chroma_data:/chroma/chroma
    restart: unless-stopped

  # ═══════════ 后端 C++ 服务 ═══════════
  fiber-backend:
    build:
      context: ./fiber-backend
      dockerfile: Dockerfile
    ports:
      - "8080:8080"   # REST API Gateway
      - "8081:8081"   # WebSocket
    volumes:
      - backend_data:/data
      - backend_logs:/var/log/fiber-backend
    restart: unless-stopped
    deploy:
      replicas: 2

  # ═══════════ Vue3 统计面板 ═══════════
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports: ["5173:5173"]
    environment:
      - DEERFLOW_API_URL=http://deerflow:8000
      - FIBER_WS_URL=ws://fiber-backend:8081
      - FIBER_REST_URL=http://fiber-backend:8080
    depends_on:
      - deerflow
      - fiber-backend
    restart: unless-stopped

  # ═══════════ 监控 ═══════════
  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports: ["3001:3000"]
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/dashboards:/etc/grafana/provisioning/dashboards
    depends_on: [prometheus]
    restart: unless-stopped

volumes:
  ollama_data:
  chroma_data:
  backend_data:
  backend_logs:
  agent_logs:
  report_tmp:
  prometheus_data:
  grafana_data:
```

### 16.3 启动顺序

```
1. ollama (LLM 推理)
2. chromadb (向量数据库)
3. fiber-backend (C++ 后端)
4. deerflow (Agent 层)
5. frontend (Vue3 面板)
6. prometheus + grafana (监控)
```

------

## 17. CI/CD 集成

### 17.1 流水线定义

```yaml
# .gitlab-ci.yml

stages:
  - test
  - build
  - deploy

# ═══════════ 每日定时测试 ═══════════
api_test:
  stage: test
  script:
    - cd tests/
    - python -m pytest test_api/ -v --html=report.html
    - python test_client.py --all --report
  artifacts:
    paths:
      - tests/reports/
    expire_in: 30 days
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'  # 每日 02:00
    - if: '$CI_PIPELINE_SOURCE == "web"'       # 手动触发
    - if: '$CI_MERGE_REQUEST_ID'               # MR 触发

# ═══════════ 构建 ═══════════
build:
  stage: build
  script:
    - docker compose build
  needs: [api_test]  # 测试通过才构建

# ═══════════ 部署 ═══════════
deploy:
  stage: deploy
  script:
    - docker compose up -d
  needs: [build]
  environment:
    name: production
```

### 17.2 测试失败处理

| 情况         | 处理                        |
| ------------ | --------------------------- |
| 测试全部通过 | 继续构建部署                |
| 测试失败     | **阻断部署** + 企业微信通知 |
| 测试超时     | 视为失败                    |
| 环境不可用   | 跳过部署 + 告警             |

------

## 18. 非功能性需求

### 18.1 性能

| 指标               | 要求                 |
| ------------------ | -------------------- |
| 单条光纤分析响应   | ≤ 10s（含 LLM 推理） |
| 批量分析（100 条） | ≤ 60s                |
| RAG 检索延迟       | ≤ 2s                 |
| MCP 单次调用       | ≤ 5s                 |
| WS 推送延迟        | ≤ 1s                 |
| 轮询同步延迟       | ≤ 10s                |
| 报告生成（PDF）    | ≤ 15s                |

### 18.2 可用性

| 指标           | 要求                     |
| -------------- | ------------------------ |
| Agent 层可用性 | ≥ 99.5%                  |
| 后端不可用时   | 离线模式（RAG 问答可用） |
| 模型降级       | 自动，用户无感知         |
| 数据持久化     | 分析结果不丢失           |

### 18.3 可扩展性

| 指标           | 要求             |
| -------------- | ---------------- |
| 连纤规模       | 支持 10 万条     |
| 单次批量       | 最大 100 条      |
| 并发 Sub-Agent | 最大 5           |
| 知识库文档     | 支持 1000+ 文档  |
| 插件扩展       | 热加载，无需重启 |

### 18.4 安全性

| 指标       | 要求                           |
| ---------- | ------------------------------ |
| 网络       | 内网部署，暂不考虑外部认证     |
| 知识库管理 | 角色权限控制（admin/operator） |
| 审计       | 全操作审计日志                 |
| 数据       | 分析结果持久化，不对外暴露     |

------

## 19. 开发路线图

### 19.1 总体计划（Phase 3: 4 周）

| 周次    | 工作                 | 产出                                        | 验收标准               |
| ------- | -------------------- | ------------------------------------------- | ---------------------- |
| **W11** | 环境 + 基础设施      | DeerFlow 运行 / OLLAMA / MCP 骨架 / 降级 MW | 模型可调用，降级可触发 |
| **W12** | Tools + MCP + MW     | 14+5 Tools / 校验 MW / 审计 MW / 单测       | 所有 Tool 可调用后端   |
| **W13** | Agent + RAG + Skills | 5 Sub-Agent / 5 Skills / 知识库 / RAG MW    | 端到端对话可用         |
| **W14** | 面板 + 导出 + 联调   | Vue3 / 导出 / 记忆 / 监控 / ETCLOVG         | 全功能验收             |

### 19.2 详细任务分解

#### W11: 环境 + 基础设施

| 天   | 任务                               | 产出       |
| ---- | ---------------------------------- | ---------- |
| D1   | DeerFlow 2.0 最新版部署 + 环境验证 | 运行环境   |
| D2   | OLLAMA 部署 qwen3.6 + 推理测试     | 模型可用   |
| D3   | config.yaml 编写 + Agent 注册      | 配置完成   |
| D4   | ModelDegradationMiddleware 开发    | 降级中间件 |
| D5   | MCP 连接器骨架 + 连通性测试        | MCP 可调通 |

#### W12: Tools + MCP + Middleware

| 天   | 任务                                   | 产出          |
| ---- | -------------------------------------- | ------------- |
| D1   | topology_tools (4 个)                  | 拓扑查询可用  |
| D2   | performance_tools + alarm_tools (3 个) | 性能/告警可用 |
| D3   | colored_tools + stats_tools (4 个)     | 颜色/统计可用 |
| D4   | FiberDomainValidationMW + AuditLogMW   | 校验/审计     |
| D5   | 全部 Tools 单元测试 + MCP 错误处理     | 测试报告      |

#### W13: Agent + RAG + Skills

| 天   | 任务                                | 产出            |
| ---- | ----------------------------------- | --------------- |
| D1   | 5 个 Sub-Agent Prompt 工程 + 注册   | Agent 可对话    |
| D2   | 5 个 Markdown Skills 编写           | Skills 文件     |
| D3   | RAG 知识库构建（6 类 16 篇文档）    | ChromaDB 初始化 |
| D4   | RAGInjectionMW + rag-retriever 调优 | 知识注入可用    |
| D5   | 端到端测试（单条/批量/趋势/巡检）   | 功能验证        |

#### W14: 面板 + 导出 + 联调

| 天   | 任务                                | 产出       |
| ---- | ----------------------------------- | ---------- |
| D1   | Vue3 统计面板（WS + 轮询 + 趋势图） | 面板可用   |
| D2   | 导出引擎（PDF/Excel/CSV）+ 下载链接 | 导出可用   |
| D3   | 记忆系统（短期 + 长期 + 对比分析）  | 记忆可用   |
| D4   | Prometheus + Grafana + 日志 + 通知  | 监控可用   |
| D5   | 全链路联调 + ETCLOVG 验证 + 文档    | 里程碑验收 |

### 19.3 后续迭代（Phase 4+）

| 迭代    | 内容                                          |
| ------- | --------------------------------------------- |
| Phase 4 | 知识库管理界面 / 插件 SDK / 多用户支持        |
| Phase 5 | Python 自测客户端完善 / CI/CD 集成 / 性能优化 |
| Phase 6 | 模拟界面评估 / 用户反馈 / 持续优化            |

------

## 20. 验收标准（ETCLOVG）

| 维度                  | 验收项   | 通过标准                                  |
| --------------------- | -------- | ----------------------------------------- |
| **E** - Environment   | 环境部署 | Docker Compose 一键启动，所有服务健康     |
| **T** - Tools         | 工具调用 | 14 个 Tool 全部可正确调用后端 API         |
| **C** - Conversation  | 对话能力 | 单条/批量/趋势/巡检/知识问答 5 类场景通过 |
| **L** - Logic         | 业务逻辑 | 颜色/衰耗结果与后端一致，无误判           |
| **O** - Output        | 输出质量 | 报告结构完整，建议合理，引用准确          |
| **V** - Visualization | 可视化   | 统计面板实时刷新，趋势图正确              |
| **G** - Graceful      | 容错降级 | 后端断开→离线模式，模型超时→自动降级      |

### 20.1 测试用例矩阵

| 场景     | 输入示例                 | 预期输出            |
| -------- | ------------------------ | ------------------- |
| 单条分析 | "分析光纤 F1001"         | 性能+衰耗+颜色+建议 |
| 批量分析 | "分析所有红色连纤"       | 列表+排序+共性问题  |
| 趋势查询 | "最近24小时趋势"         | 趋势图+异常点+建议  |
| 对比分析 | "F1001 今天和上周对比"   | 变化量+趋势+建议    |
| 巡检     | "巡检网元 NE101"         | 健康评分+问题清单   |
| 知识问答 | "单模光纤告警阈值是多少" | RAG 检索结果        |
| 导出     | "导出报告为 PDF"         | 下载链接            |
| 离线     | 后端断开后提问           | 友好提示 + RAG 可用 |
| 降级     | 模型超时                 | 自动降级，用户无感  |
| 上下文   | "那 F1002 呢？"          | 正确理解省略意图    |

------

## 21. 附录

### 21.1 项目目录结构（最终版）

```
fiber-maintenance-agent/
│
├── deer-flow/                              # DeerFlow 2.0 Agent 层
│   ├── backend/packages/harness/deerflow/
│   │   ├── agents/
│   │   │   └── lead_agent/
│   │   │       └── agent.py                # Lead Agent
│   │   ├── tools/
│   │   │   ├── builtins/                   # DeerFlow 内置
│   │   │   └── fiber/                      # ★ 自定义 Tools
│   │   │       ├── __init__.py
│   │   │       ├── topology_tools.py       # 4 tools
│   │   │       ├── performance_tools.py    # 2 tools
│   │   │       ├── alarm_tools.py          # 1 tool
│   │   │       ├── colored_tools.py        # 2 tools
│   │   │       ├── stats_tools.py          # 2 tools
│   │   │       ├── rag_tools.py            # 3 tools
│   │   │       ├── export_tools.py         # 3 tools (PDF/Excel/CSV)
│   │   │       └── memory_tools.py         # 2 tools (save/query)
│   │   ├── middlewares/fiber/              # ★ 4 Middleware
│   │   │   ├── __init__.py
│   │   │   ├── model_degradation.py
│   │   │   ├── domain_validation.py
│   │   │   ├── rag_injection.py
│   │   │   └── audit_log.py
│   │   ├── skills/                         # ★ 5 Skills
│   │   │   ├── fiber_spanloss_analysis.md
│   │   │   ├── fiber_color_diagnosis.md
│   │   │   ├── batch_fiber_analysis.md
│   │   │   ├── fiber_trend_analysis.md
│   │   │   └── ne_health_check.md
│   │   ├── memory/
│   │   │   └── fiber_memory.py             # 记忆系统
│   │   ├── mcp/
│   │   │   └── fiber_backend.py            # MCP 连接器
│   │   ├── export/
│   │   │   ├── pdf_exporter.py
│   │   │   ├── excel_exporter.py
│   │   │   └── csv_exporter.py
│   │   └── plugins/                        # ★ 插件目录
│   │       ├── tools/                      # Tool 插件（自动发现）
│   │       └── agents/                     # Agent 插件（自动发现）
│   └── Dockerfile
│
├── knowledge_base/                         # ★ RAG 知识库
│   ├── 01_设备技术手册/
│   ├── 02_维护操作规范/
│   ├── 03_告警处理指南/
│   ├── 04_历史故障案例/
│   ├── 05_衰耗阈值标准/
│   └── 06_网元配置规范/
│
├── frontend/                               # ★ Vue3 统计面板
│   ├── src/
│   │   ├── composables/
│   │   │   ├── useFiberStats.ts            # WS 订阅 + 轮询
│   │   │   └── useTrendData.ts             # 趋势数据
│   │   ├── components/
│   │   │   ├── StatsOverview.vue
│   │   │   ├── TrendChart.vue
│   │   │   ├── RecentChanges.vue
│   │   │   ├── AlarmList.vue
│   │   │   └── FiberDetail.vue
│   │   ├── views/
│   │   │   ├── Dashboard.vue
│   │   │   └── KnowledgeAdmin.vue          # 知识库管理
│   │   └── App.vue
│   └── Dockerfile
│
├── fiber-backend/                          # 后端 C++ (已实现)
│   └── Dockerfile
│
├── tests/                                  # ★ 测试
│   ├── test_api/                           # API 接口测试
│   │   ├── test_topology.py
│   │   ├── test_performance.py
│   │   ├── test_alarm.py
│   │   ├── test_colored.py
│   │   ├── test_stats.py
│   │   └── test_websocket.py
│   ├── test_agent/                         # Agent 层测试
│   │   ├── test_tools.py
│   │   ├── test_middlewares.py
│   │   ├── test_rag.py
│   │   └── test_memory.py
│   ├── test_client.py                      # ★ Python 自测客户端
│   ├── data_injector.py                    # 模拟数据注入
│   └── conftest.py
│
├── monitoring/                             # ★ 监控配置
│   ├── prometheus.yml
│   └── dashboards/
│       ├── agent_overview.json
│       ├── fiber_status.json
│       └── llm_inference.json
│
├── docs/                                   # ★ 文档
│   ├── PLUGIN_SDK.md                       # 插件开发指南
│   ├── API_REFERENCE.md                    # 接口参考
│   ├── DEPLOYMENT.md                       # 部署指南
│   └── USER_GUIDE.md                       # 用户手册
│
├── config.yaml                             # ★ 主配置
├── docker-compose.yaml                     # ★ 部署编排
├── .gitlab-ci.yml                          # ★ CI/CD
├── Makefile                                # 常用命令
└── README.md
```

### 21.2 接口速查表

| 接口       | 方法 | 路径                                               | 用途              |
| ---------- | ---- | -------------------------------------------------- | ----------------- |
| 查询连纤   | GET  | `/api/v1/topology/fibers/{fiber_id}`               | 单条连纤信息      |
| 批量连纤   | POST | `/api/v1/topology/fibers/batch`                    | 批量查询(max 100) |
| 查询单盘   | GET  | `/api/v1/boards/{board_id}`                        | 单盘信息          |
| 批量单盘   | POST | `/api/v1/boards/batch`                             | 批量查询          |
| 光纤性能   | GET  | `/api/v1/fibers/{fiber_id}/performance`            | OOP/IOP           |
| 光纤衰耗   | GET  | `/api/v1/fibers/{fiber_id}/spanloss`               | 衰耗值            |
| 有颜色连纤 | GET  | `/api/v1/fibers/colored?color=RED|YELLOW`          | 按颜色筛选        |
| 全部有颜色 | GET  | `/api/v1/fibers/colored/all`                       | 全部              |
| 实时统计   | GET  | `/api/v1/fibers/stats/realtime`                    | 红/黄数量         |
| 趋势查询   | GET  | `/api/v1/fibers/stats/trend?start_time=&end_time=` | 时序数据          |
| 告警查询   | GET  | `/api/v1/alarms/current?board_id=&port_id=`        | 当前告警          |
| WebSocket  | WS   | `ws://host:8081/ws/v1/events`                      | 实时事件推送      |

### 21.3 配置速查

| 配置项         | 值                  |
| -------------- | ------------------- |
| LLM 模型       | qwen3.6 (OLLAMA)    |
| LLM 端口       | :11434              |
| Agent API      | :8000               |
| Agent Web UI   | :3000               |
| 后端 REST      | :8080               |
| 后端 WS        | :8081               |
| 前端面板       | :5173               |
| ChromaDB       | :8100               |
| Prometheus     | :9090               |
| Grafana        | :3001               |
| MCP 超时       | 5s                  |
| MCP 重试       | 2 次                |
| 并发 Sub-Agent | 5                   |
| 批量上限       | 100 条              |
| 排队策略       | FIFO                |
| 短期记忆       | 50 条               |
| RAG Top-K      | 3                   |
| 轮询间隔       | 10s                 |
| WS 心跳        | 15s                 |
| 报告保留       | 24h                 |
| 日志保留       | 审计 90d / 运行 30d |

### 21.4 术语表

| 术语       | 含义                                                 |
| ---------- | ---------------------------------------------------- |
| OOP        | Output Optical Power，源端输出光功率 (dBm)           |
| IOP        | Input Optical Power，宿端输入光功率 (dBm)            |
| Spanloss   | 光纤衰耗 (dB)，由后端计算                            |
| 有源盘     | 需要供电的光纤设备单盘                               |
| 无源盘     | 无需供电的光纤配线单盘（3 端口）                     |
| 网元间连纤 | 不同网元之间的光纤连接（Agent 操作对象）             |
| 网元内连纤 | 同一网元内部连接（Agent 不处理）                     |
| 颜色       | 光纤健康状态标识（绿/黄/红），由后端判定             |
| 场景       | 连纤拓扑类型（后端判定，Agent 仅展示）               |
| DeerFlow   | 开源 AI Agent 框架（本系统基座）                     |
| MCP        | Model Context Protocol，模型上下文协议               |
| RAG        | Retrieval-Augmented Generation，检索增强生成         |
| ETCLOVG    | 验收标准缩写（环境/工具/对话/逻辑/输出/可视化/容错） |

------

## 文档变更记录

| 版本     | 日期           | 变更内容                                                     |
| -------- | -------------- | ------------------------------------------------------------ |
| v1.0     | —              | 原始需求规格说明书                                           |
| v2.0     | 2026-07-21     | 三轮澄清后修订（移除沙箱/独立推送/场景判定）                 |
| **v3.0** | **2026-07-21** | **最终版：新增导出/记忆/对比/插件化/监控/CI-CD/知识库管理/容错** |

------

> **本文档为最终确认版本，作为后续编码实施的唯一基准。**
> **如需变更，须通过正式变更流程审批。**