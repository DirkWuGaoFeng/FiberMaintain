# 光纤维护服务系统 Agent 详细设计报告 v3.2

------

## 文档信息

| 项目     | 内容                                                         |
| -------- | ------------------------------------------------------------ |
| 文档名称 | 光纤维护服务系统 Agent 详细设计报告                          |
| 版本号   | v3.2                                                         |
| 基线文档 | 需求规格说明书 v3.0（DeerFlow 2.0 版）                       |
| 前序版本 | 详细设计报告 v3.1                                            |
| 编制日期 | 2026-07-24                                                   |
| 变更说明 | 基于 v3.1 评审结论，落实三项决策：①批量处理对齐主流工程标准；②沙箱确认为设计扩展；③analysis-expert 温度降至 0.1 |

------

## 修订记录

| 版本 | 日期       | 变更内容                                             | 变更原因       |
| ---- | ---------- | ---------------------------------------------------- | -------------- |
| v3.1 | 2026-07    | 初版详细设计                                         | 需求 v3.0 落地 |
| v3.2 | 2026-07-24 | 批量处理工程标准化；沙箱定性为设计扩展；温度参数调整 | 评审决策落实   |

------

## 目录

1. [设计总览](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#1-设计总览)
2. [系统架构设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#2-系统架构设计)
3. [Sub-Agent 详细设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#3-sub-agent-详细设计)
4. [批量处理工程设计（重点修订）](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#4-批量处理工程设计重点修订)
5. [LLM 参数配置策略（重点修订）](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#5-llm-参数配置策略重点修订)
6. [沙箱模块设计（设计扩展）](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#6-沙箱模块设计设计扩展)
7. [MCP 连接器设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#7-mcp-连接器设计)
8. [中间件管道设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#8-中间件管道设计)
9. [记忆系统设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#9-记忆系统设计)
10. [RAG 知识检索设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#10-rag-知识检索设计)
11. [容错与降级设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#11-容错与降级设计)
12. [数据库设计](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#12-数据库设计)
13. [部署架构](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#13-部署架构)
14. [测试策略](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#14-测试策略)
15. [与需求基线一致性矩阵](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#15-与需求基线一致性矩阵)
16. [附录](https://www.qianwen.com/chat/2ffe35d49a364beda7e6de07bcdb909a#16-附录)

------

## 1. 设计总览

### 1.1 设计目标

基于需求规格说明书 v3.0，将光纤维护服务 Agent 从"做什么"推进到"怎么做"，输出可直接指导编码的工程级设计。

### 1.2 核心设计原则

| #    | 原则           | 说明                                                         |
| ---- | -------------- | ------------------------------------------------------------ |
| P1   | Agent 不做计算 | 所有数值计算由后端完成，Agent 仅做语义理解、调度编排、结果表述 |
| P2   | 单一数据出口   | 所有后端数据必须经 data-collector 获取，禁止其他 Sub-Agent 直连后端 |
| P3   | 批量工程标准化 | 批量处理遵循分块-游标-背压-幂等四要素，对齐主流工程实践      |
| P4   | 确定性优先     | 分析类任务温度 0.1，确保同数据同结论，可审计可复现           |
| P5   | 四级容错       | 正常 → 模型降级 → 规则兜底 → 纯知识模式，覆盖全故障谱        |
| P6   | 轻量存储       | 记忆仅存关键指标快照，适配单用户 SQLite 场景                 |

### 1.3 v3.2 关键变更摘要

| 变更项               | v3.1                 | v3.2                                                  | 变更依据            |
| -------------------- | -------------------- | ----------------------------------------------------- | ------------------- |
| 批量处理策略         | 单实例批量，上限 200 | **分块处理（Chunk）+ 游标分页 + 背压控制**，块大小 50 | 主流工程标准        |
| 沙箱模块             | 预留接口，默认关闭   | **确认为设计扩展**，独立章节说明                      | 评审决策            |
| analysis-expert 温度 | 0.3                  | **0.1**                                               | 确定性/可审计性要求 |

------

## 2. 系统架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                                │
│                   (Web UI / API Gateway)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                     Lead Agent (编排层)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ 意图识别  │ │ 任务分解  │ │ 调度编排  │ │ 结果聚合 & 表述  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  中间件管道: Auth → Domain → RateLimit → RAGInjection           │
└───┬──────────┬──────────┬──────────┬────────────────────────────┘
    │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼──────────┐
│ data- │ │analysis│ │report-│ │  knowledge-  │
│collector│ │-expert │ │generator│ │  assistant  │
└───┬───┘ └───┬───┘ └───┬───┘ └───┬──────────┘
    │          │          │          │
┌───▼──────────▼──────────▼──────────▼────────────────────────────┐
│                    MCP Server (数据接入层)                       │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐   │
│  │ 光纤性能 API    │  │ 告警/板卡 API   │  │  RAG 知识库      │   │
│  └────────────────┘  └────────────────┘  └──────────────────┘   │
│  熔断器 │ 负载感知 │ 退避重试 │ 超时分级                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    后端业务系统 (REST API)                       │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Sub-Agent 注册表（4 个）

| Sub-Agent           | 职责             | 温度    | 工具集                                                       |
| ------------------- | ---------------- | ------- | ------------------------------------------------------------ |
| data-collector      | 数据获取唯一出口 | 0.0     | fiber_performance_query, batch_fiber_performance_query, fiber_spanloss_query, batch_fiber_spanloss_query, colored_fibers_query, fiber_trend_query, alarm_query, batch_alarm_query, board_query, batch_board_query |
| analysis-expert     | 数据分析解读     | **0.1** | memory_query, memory_save, sandbox_exec（预留）              |
| report-generator    | 报告生成         | 0.3     | rag_query, memory_query                                      |
| knowledge-assistant | 知识问答         | 0.5     | rag_query, memory_query                                      |

### 2.3 三级实例化模型

```
┌─────────────────────────────────────────────────────┐
│  L1 注册层（静态常驻）                                │
│  - 4 个 Sub-Agent 定义注册于 Lead Agent              │
│  - 零资源占用，仅保存元数据（名称/描述/工具清单）      │
└──────────────────────┬──────────────────────────────┘
                       │ 按需创建
┌──────────────────────▼──────────────────────────────┐
│  L2 执行层（按需创建/销毁）                           │
│  - 用户请求触发时实例化对应 Sub-Agent                 │
│  - 任务完成后销毁，释放上下文窗口                     │
│  - 生命周期 ≤ 单次请求                               │
└──────────────────────┬──────────────────────────────┘
                       │ 批量场景
┌──────────────────────▼──────────────────────────────┐
│  L3 批量层（分块迭代）                               │
│  - 单实例内按 Chunk 迭代处理                         │
│  - 每 Chunk 完成后释放中间数据                       │
│  - 禁止为每条记录创建独立实例                        │
└─────────────────────────────────────────────────────┘
```

------

## 3. Sub-Agent 详细设计

### 3.1 data-collector（数据采集器）

**职责**：作为系统与后端 API 之间的唯一数据通道。

**设计约束**：

- 温度 = 0.0（纯工具调用，无需创造性）
- 不做任何数据解读或计算
- 返回结构化 JSON，由 analysis-expert 消费
- 支持单条查询和批量分块查询两种模式

**工具清单**：

| 工具名                        | 类型 | 超时  | 说明                    |
| ----------------------------- | ---- | ----- | ----------------------- |
| fiber_performance_query       | 单条 | 2s    | 查询单条光纤性能数据    |
| batch_fiber_performance_query | 批量 | 5s/块 | 分块批量查询，块大小 50 |
| fiber_spanloss_query          | 单条 | 2s    | 查询单条光纤跨段损耗    |
| batch_fiber_spanloss_query    | 批量 | 5s/块 | 分块批量查询跨段损耗    |
| colored_fibers_query          | 单条 | 2s    | 查询着色光纤列表        |
| fiber_trend_query             | 单条 | 3s    | 查询光纤趋势数据        |
| alarm_query                   | 单条 | 2s    | 查询告警信息            |
| batch_alarm_query             | 批量 | 5s/块 | 分块批量查询告警        |
| board_query                   | 单条 | 2s    | 查询板卡信息            |
| batch_board_query             | 批量 | 5s/块 | 分块批量查询板卡        |

### 3.2 analysis-expert（分析专家）

**职责**：接收 data-collector 传入的结构化数据，进行语义分析、趋势解读、异常判定。

**设计约束**：

- **温度 = 0.1**（详见第 5 章）
- **禁止直接调用后端 API**，仅接受 data-collector 传入的数据
- 分析结论必须可溯源至具体数据字段
- 不做数值计算（如平均值、百分比变化），仅做语义解读

**工具清单**：

| 工具名       | 说明                                  |
| ------------ | ------------------------------------- |
| memory_query | 查询历史分析记忆（用于趋势对比）      |
| memory_save  | 异步保存分析快照                      |
| sandbox_exec | 预留沙箱执行（默认关闭，详见第 6 章） |

**System Prompt 核心指令**：

```
你是光纤维护数据分析专家。你的职责是：
1. 解读 data-collector 提供的结构化数据
2. 识别异常模式（损耗突增、颜色劣化、趋势偏离）
3. 给出维护建议（基于数据，不做数值计算）
4. 所有结论必须引用具体数据字段作为依据

【严格禁止】
- 不得编造数据中不存在的数值
- 不得进行数学计算（如"增长了15%"需后端提供）
- 不得直接调用后端 API
```

### 3.3 report-generator（报告生成器）

**职责**：将分析结果组织为用户可读的报告格式。

**设计约束**：

- 温度 = 0.3（允许适度的表述灵活性）
- 可按需调用 rag_query 获取规范引用
- 报告结构固定：摘要 → 数据概览 → 异常分析 → 建议 → 参考规范

### 3.4 knowledge-assistant（知识助手）

**职责**：回答光纤维护领域的知识性问题。

**设计约束**：

- 温度 = 0.5（知识问答允许适度发散）
- 仅使用 RAG 知识库内容，不编造知识
- 无法回答时明确告知"知识库中未找到相关信息"

------

## 4. 批量处理工程设计（重点修订）

### 4.1 设计决策说明

> **v3.1 问题**：批量上限 200 条，单实例一次性处理。当数据量较大时，存在以下风险：
>
> - 超出 LLM 上下文窗口（8K tokens）
> - 单次请求耗时过长，用户体验差
> - 后端压力集中，缺乏背压保护
> - 部分失败时无法断点续传
>
> **v3.2 决策**：对齐主流工程标准，采用 **分块（Chunking）+ 游标分页（Cursor Pagination）+ 背压控制（Backpressure）+ 幂等保障（Idempotency）** 四要素模型。

### 4.2 批量处理四要素模型

```
┌─────────────────────────────────────────────────────────────┐
│                    批量处理引擎                               │
│                                                             │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │ Chunk 1 │───▶│ Chunk 2 │───▶│ Chunk 3 │───▶│ Chunk N │  │
│  │ (50条)  │    │ (50条)  │    │ (50条)  │    │ (≤50条) │  │
│  └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘  │
│       │              │              │              │        │
│       ▼              ▼              ▼              ▼        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              聚合层（Aggregator）                     │    │
│  │   统计摘要 + Top-N 异常明细 + 进度报告               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  控制机制:                                                   │
│  • 游标分页: cursor_id 标记已处理位置                        │
│  • 背压控制: 后端错误率 > 10% 时暂停取数                    │
│  • 幂等保障: 每 Chunk 带 chunk_id，重试不重复处理            │
│  • 进度上报: 每 Chunk 完成后向用户推送进度                   │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 核心参数配置

| 参数              | 值        | 说明                                      |
| ----------------- | --------- | ----------------------------------------- |
| CHUNK_SIZE        | **50**    | 每块处理记录数（主流工程标准：50~100）    |
| MAX_BATCH_TOTAL   | **200**   | 单次批量请求最大总量                      |
| MAX_CHUNKS        | **4**     | 最大分块数 = MAX_BATCH_TOTAL / CHUNK_SIZE |
| CHUNK_TIMEOUT     | **5s**    | 单块请求超时                              |
| INTER_CHUNK_DELAY | **200ms** | 块间间隔（背压缓冲）                      |
| PROGRESS_INTERVAL | **每块**  | 进度上报频率                              |
| CURSOR_TTL        | **300s**  | 游标有效期（断点续传窗口）                |

### 4.4 分块处理流程

```python
# 伪代码：批量处理引擎核心逻辑
async def batch_process(fiber_ids: list, chunk_size=50):
    total = len(fiber_ids)
    assert total <= MAX_BATCH_TOTAL, f"超出批量上限 {MAX_BATCH_TOTAL}"
    
    cursor_id = generate_cursor()  # 生成游标
    results = []
    chunk_index = 0
    
    for chunk in chunked(fiber_ids, chunk_size):
        chunk_index += 1
        chunk_id = f"{cursor_id}_chunk_{chunk_index}"
        
        # 1. 背压检查
        if backpressure_checker.is_throttled():
            await asyncio.sleep(backpressure_checker.get_wait_time())
        
        # 2. 幂等检查（是否已处理过）
        if idempotency_store.exists(chunk_id):
            results.append(idempotency_store.get(chunk_id))
            continue
        
        # 3. 调用 data-collector 批量工具
        try:
            chunk_result = await data_collector.batch_query(
                fiber_ids=chunk,
                chunk_id=chunk_id,
                timeout=CHUNK_TIMEOUT
            )
            # 4. 记录幂等标记
            idempotency_store.save(chunk_id, chunk_result, ttl=CURSOR_TTL)
            results.append(chunk_result)
            
        except TimeoutError:
            # 5. 超时重试（最多 2 次，退避 500ms → 1000ms）
            chunk_result = await retry_with_backoff(chunk, chunk_id)
            results.append(chunk_result)
        
        # 6. 进度上报
        await progress_reporter.report(
            processed=chunk_index * chunk_size,
            total=total,
            percentage=round(chunk_index * chunk_size / total * 100)
        )
        
        # 7. 块间延迟（背压缓冲）
        await asyncio.sleep(INTER_CHUNK_DELAY)
    
    # 8. 聚合
    return aggregator.summarize(results)
```

### 4.5 聚合策略（解决上下文窗口限制）

> **核心问题**：200 条数据全量传入 LLM 会超出 8K 上下文窗口。
>
> **解决方案**：分层聚合，LLM 仅处理摘要 + 异常明细。

```
┌─────────────────────────────────────────────────────────┐
│                    聚合策略                              │
│                                                         │
│  输入: N 条原始数据（最多 200 条）                       │
│                                                         │
│  第一层: 程序化统计（不经过 LLM）                        │
│  ├── 总数 / 正常数 / 异常数 / 各色占比                  │
│  ├── 损耗均值 / 最大值 / 最小值（后端计算）             │
│  └── 趋势方向（上升/下降/平稳，后端标记）               │
│                                                         │
│  第二层: 异常筛选（不经过 LLM）                          │
│  ├── 红色光纤列表（全量）                               │
│  ├── 损耗突增 Top-10（按增幅排序）                      │
│  └── 新增告警列表（全量）                               │
│                                                         │
│  第三层: LLM 分析（仅传入摘要 + 异常明细）              │
│  ├── 输入 tokens ≈ 统计摘要(500) + 异常明细(2000)      │
│  │                + 历史对比(500) + 指令(500)           │
│  │                ≈ 3500 tokens（远低于 8K 上限）       │
│  └── 输出: 分析解读 + 维护建议                          │
│                                                         │
│  最终输出:                                              │
│  ├── 统计概览（程序化生成，确定性）                     │
│  ├── 异常分析（LLM 生成，温度 0.1）                    │
│  └── 完整数据附表（原始数据透传，不经 LLM）             │
└─────────────────────────────────────────────────────────┘
```

### 4.6 游标分页设计

| 字段          | 类型         | 说明                                      |
| ------------- | ------------ | ----------------------------------------- |
| cursor_id     | string(UUID) | 本次批量任务唯一标识                      |
| chunk_index   | int          | 当前块序号（从 1 开始）                   |
| chunk_size    | int          | 当前块大小                                |
| processed_ids | list[string] | 已处理的光纤 ID 列表                      |
| status        | enum         | PENDING / PROCESSING / COMPLETED / FAILED |
| created_at    | timestamp    | 游标创建时间                              |
| expires_at    | timestamp    | 游标过期时间（created_at + 300s）         |

**断点续传**：若处理中断（如网络断开），用户重新发起相同请求时，系统检查 cursor_id 是否有效，从上次完成的 chunk_index + 1 继续处理。

### 4.7 背压控制机制

```
┌─────────────────────────────────────────────────────────┐
│                  背压控制器                               │
│                                                         │
│  监控指标: 1 分钟滑动窗口内后端 5xx 错误率              │
│                                                         │
│  状态机:                                                │
│  ┌────────┐  错误率>10%  ┌──────────┐  错误率<3%   ┌────────┐
│  │ NORMAL │────────────▶│THROTTLED │─────────────▶│RECOVER │
│  │并发=5  │             │ 并发=2   │  持续60s     │并发=3  │
│  └────────┘             └──────────┘              └───┬────┘
│       ▲                                              │
│       │              持续60s 错误率<3%                │
│       └──────────────────────────────────────────────┘
│                                                         │
│  块间行为:                                              │
│  - NORMAL:    INTER_CHUNK_DELAY = 200ms                │
│  - THROTTLED: INTER_CHUNK_DELAY = 1000ms + 并发降至 2  │
│  - RECOVER:   INTER_CHUNK_DELAY = 500ms + 并发 = 3    │
└─────────────────────────────────────────────────────────┘
```

### 4.8 幂等保障

| 机制       | 实现方式                                                     |
| ---------- | ------------------------------------------------------------ |
| 请求级幂等 | 每个批量请求携带 client_request_id（UUID），服务端去重       |
| 块级幂等   | 每个 Chunk 携带 chunk_id = `{cursor_id}_chunk_{index}`，已完成的块不重复执行 |
| 存储级幂等 | 幂等标记存储于 Redis/内存 Map，TTL = CURSOR_TTL（300s）      |
| 重试安全   | 重试时先检查幂等标记，已完成则直接返回缓存结果               |

### 4.9 批量工具接口规范

以 `batch_fiber_performance_query` 为例：

**请求**：

```json
{
  "fiber_ids": ["F001", "F002", "...", "F050"],
  "chunk_id": "uuid_chunk_1",
  "cursor_id": "uuid_batch_task",
  "chunk_index": 1,
  "total_chunks": 4
}
```

**响应**：

```json
{
  "chunk_id": "uuid_chunk_1",
  "status": "success",
  "data": [
    {"fiber_id": "F001", "spanloss": 12.5, "color": "green", "...": "..."},
    "..."
  ],
  "count": 50,
  "next_cursor": "uuid_chunk_2"
}
```

**错误响应**：

```json
{
  "chunk_id": "uuid_chunk_1",
  "status": "partial_failure",
  "data": ["...成功数据..."],
  "failed_ids": ["F023", "F047"],
  "error": "TIMEOUT on 2 records",
  "retryable": true
}
```

### 4.10 部分失败处理

| 失败比例            | 处理策略                                                    |
| ------------------- | ----------------------------------------------------------- |
| 0%（全部成功）      | 正常进入下一 Chunk                                          |
| 1%~20%（部分失败）  | 失败记录加入重试队列，当前 Chunk 成功部分正常聚合           |
| 21%~50%（较多失败） | 当前 Chunk 标记为 DEGRADED，重试 1 次后继续                 |
| >50%（大面积失败）  | 触发背压，暂停 5s 后重试；连续 2 次大面积失败则终止批量任务 |

**重试队列**：

- 所有 Chunk 处理完毕后，统一重试失败记录
- 重试仍失败则标记为 `UNAVAILABLE`，在最终报告中标注"以下光纤数据暂时不可用"

------

## 5. LLM 参数配置策略（重点修订）

### 5.1 温度参数总表

| Sub-Agent           | 温度    | top_p   | 理由                       |
| ------------------- | ------- | ------- | -------------------------- |
| data-collector      | 0.0     | 1.0     | 纯工具调用，无需生成文本   |
| **analysis-expert** | **0.1** | **0.3** | **确定性分析（详见 5.2）** |
| report-generator    | 0.3     | 0.8     | 报告表述允许适度灵活       |
| knowledge-assistant | 0.5     | 0.9     | 知识问答允许适度发散       |
| Lead Agent（编排）  | 0.0     | 1.0     | 任务分解需确定性           |

### 5.2 analysis-expert 温度降至 0.1 的详细说明

#### 5.2.1 变更内容

| 项目        | v3.1 | v3.2    |
| ----------- | ---- | ------- |
| temperature | 0.3  | **0.1** |
| top_p       | 0.8  | **0.3** |

#### 5.2.2 变更原因（五维度论证）

**① 确定性要求（Determinism）**

光纤维护分析属于**确定性任务**（Deterministic Task），与代码生成、数学推导、事实问答同类。根据 LLM 工程实践共识：

> 确定性任务（代码、公式、事实回答、数据分析）：temperature = 0.1~0.3，top_p = 0.1~0.3
> ——《LLM 调参必知：Temperature 与 Top-p 参数详解》

analysis-expert 的核心工作是"解读后端提供的确定性数据"，而非"创造性生成内容"。同一组损耗数据，无论分析多少次，结论应当一致。温度 0.3 引入了不必要的随机性，可能导致：

- 同一光纤今天分析为"轻微劣化"，明天分析为"需要关注"
- 运维人员无法信任分析结论的稳定性

**② 可审计性要求（Auditability）**

光纤维护属于**关键基础设施运维**场景，分析结论可能被用于：

- 维护工单派发依据
- 故障复盘报告引用
- 监管审计材料

温度 0.1 确保：**相同输入 → 相同输出**，满足审计追溯要求。若温度 0.3，同一数据在不同时间分析可能产生不同措辞的结论，给审计带来困扰。

**③ 幻觉抑制（Hallucination Suppression）**

温度参数直接影响模型的"创造性"程度：

- 温度越高 → 概率分布越平坦 → 低概率 token 被选中概率增大 → 幻觉风险上升
- 温度 0.1 → 概率分布极度尖锐 → 几乎只选最高概率 token → 幻觉风险最低

在数据分析场景中，幻觉表现为"编造数据中不存在的趋势或数值"。温度 0.1 配合 top_p=0.3，将采样范围严格限制在最高概率的 30% token 内，最大程度抑制幻觉。

**④ 一致性要求（Consistency）**

批量分析 200 条光纤时，analysis-expert 需要对每条光纤给出判定。若温度 0.3：

- 相同损耗值（如 15.2dB）的光纤，可能因采样随机性得到不同判定
- 用户会质疑："为什么同样 15.2dB，一个说正常，一个说异常？"

温度 0.1 确保：**相同数据特征 → 相同判定结论**，维护分析标准的统一性。

**⑤ 与系统原则 P1 的对齐**

系统核心原则 P1 明确"Agent 不做计算"，analysis-expert 的角色是**数据解读器**而非**内容创作者**。其输出应当是：

- 对后端数据的语义化表述（"该光纤损耗从 12dB 上升至 18dB"）
- 基于规则的异常判定（"超过阈值 15dB，标记为红色"）
- 基于模式的趋势解读（"连续 3 次上升，呈劣化趋势"）

这些都是**低创造性、高确定性**任务，温度 0.1 是最优选择。

#### 5.2.3 不设为 0.0 的原因

| 考虑                   | 说明                                                         |
| ---------------------- | ------------------------------------------------------------ |
| 避免完全贪婪解码的退化 | temperature=0 在某些模型实现中会触发贪婪解码，可能导致重复 token 循环 |
| 保留极微小的表述灵活性 | 0.1 允许在"该光纤呈现劣化趋势"和"该光纤损耗呈上升趋势"之间自然选择，避免机械感 |
| 工程实践共识           | 主流工程实践中，确定性任务推荐 0.1 而非 0.0（0.0 留给纯工具调用场景） |

#### 5.2.4 配套措施

| 措施         | 说明                                                         |
| ------------ | ------------------------------------------------------------ |
| top_p = 0.3  | 进一步收窄采样范围，仅从概率最高的 30% token 中选取          |
| seed 固定    | 生产环境设置固定 seed（如 42），确保完全可复现               |
| 结论锚定     | Prompt 中明确要求"结论必须引用具体数据字段"，减少自由发挥空间 |
| 输出格式约束 | 强制 JSON Schema 输出，限制自由文本区域                      |

### 5.3 各场景温度选择依据汇总

| 任务类型      | 创造性需求 | 确定性需求 | 推荐温度 | 本系统对应                 |
| ------------- | ---------- | ---------- | -------- | -------------------------- |
| 工具调用/路由 | 无         | 极高       | 0.0      | data-collector, Lead Agent |
| 数据分析/判定 | 极低       | 高         | **0.1**  | **analysis-expert**        |
| 报告撰写      | 低         | 中         | 0.3      | report-generator           |
| 知识问答      | 中         | 中         | 0.5      | knowledge-assistant        |
| 创意写作      | 高         | 低         | 0.8~1.2  | 本系统不涉及               |

------

## 6. 沙箱模块设计（设计扩展）

### 6.1 定性说明

> **设计扩展声明**：需求规格说明书 v3.0 需求澄清 Q3 明确结论为"移除沙箱脚本"。本章节内容为**设计扩展（Design Extension）**，不属于需求基线范围，不影响核心业务流程。
>
> 扩展目的：为未来可能的数据分析增强（如自定义统计脚本、可视化图表生成）预留技术接口，降低后续扩展的架构改动成本。

### 6.2 设计约束

| 约束项       | 说明                                                       |
| ------------ | ---------------------------------------------------------- |
| 默认状态     | **关闭**（配置项 `sandbox.enabled = false`）               |
| 启用条件     | 需管理员手动修改配置 + 重启服务                            |
| 业务流程影响 | **零影响**——关闭状态下 sandbox_exec 工具不注册，LLM 不可见 |
| 需求追溯     | 不关联任何需求条目，纯技术预留                             |

### 6.3 架构设计（预留）

```
┌─────────────────────────────────────────────┐
│           analysis-expert                    │
│                                             │
│  if sandbox.enabled:                        │
│    register_tool(sandbox_exec)              │
│  else:                                      │
│    # 工具不注册，LLM 无法感知               │
│    pass                                     │
└──────────────────┬──────────────────────────┘
                   │ (仅启用时)
┌──────────────────▼──────────────────────────┐
│           Sandbox Runtime                    │
│                                             │
│  隔离方式: Docker 容器                       │
│  资源限制:                                   │
│    - 内存: 512MB                            │
│    - CPU: 0.5 核                            │
│    - 执行超时: 30s                          │
│    - 网络: 禁止（无外网访问）               │
│    - 文件系统: 只读挂载 + tmpfs 写入        │
│                                             │
│  支持语言: Python 3.11（仅标准库 + numpy）  │
│  输入: JSON 格式数据                        │
│  输出: JSON 格式结果                        │
│                                             │
│  安全策略:                                   │
│    - 禁止 import os, subprocess, socket     │
│    - 禁止文件 I/O（除 tmpfs）              │
│    - 禁止网络请求                           │
│    - 执行超时强制 kill                      │
└─────────────────────────────────────────────┘
```

### 6.4 配置项

```yaml
# config.yaml
sandbox:
  enabled: false          # 默认关闭
  runtime: docker         # 隔离运行时
  image: fiber-sandbox:1.0  # 沙箱镜像
  memory_limit: 512m      # 内存上限
  cpu_limit: 0.5          # CPU 上限
  timeout: 30             # 执行超时（秒）
  network: disabled       # 网络访问
  allowed_packages:       # 允许的 Python 包
    - numpy
    - pandas
```

### 6.5 未来启用场景（仅供参考）

| 场景       | 说明                                 | 优先级 |
| ---------- | ------------------------------------ | ------ |
| 自定义统计 | 用户需要非标准统计（如滑动窗口均值） | 低     |
| 数据可视化 | 生成损耗趋势图表                     | 低     |
| 规则验证   | 执行自定义告警规则脚本               | 低     |

> ⚠️ 以上场景均为假设性扩展，当前版本不实现、不测试、不部署。

------

## 7. MCP 连接器设计

### 7.1 部署模式

| 环境      | 部署方式 | 端口  | 说明                 |
| --------- | -------- | ----- | -------------------- |
| 开发/测试 | 进程内嵌 | —     | 减少部署复杂度       |
| 生产      | 独立服务 | :8088 | 独立扩缩容、故障隔离 |

### 7.2 超时分级

| 请求类型             | 超时时间 | 说明                |
| -------------------- | -------- | ------------------- |
| 单条查询             | 2s       | 简单 GET 请求       |
| 批量查询（单 Chunk） | 5s       | 50 条数据的批量请求 |
| 趋势查询             | 3s       | 涉及时间序列计算    |
| RAG 检索             | 3s       | 向量检索 + 重排序   |

### 7.3 重试策略

```
┌─────────────────────────────────────────────────────────┐
│                    重试决策树                             │
│                                                         │
│  请求失败                                               │
│  ├── HTTP 4xx（客户端错误）                             │
│  │   ├── 400 Bad Request → 不重试，返回参数错误         │
│  │   ├── 404 Not Found → 不重试，返回数据不存在         │
│  │   └── 429 Too Many Requests → 等待 Retry-After 后重试│
│  │                                                      │
│  ├── HTTP 5xx（服务端错误）                             │
│  │   ├── 第 1 次重试: 等待 500ms                       │
│  │   ├── 第 2 次重试: 等待 1000ms                      │
│  │   └── 第 3 次: 放弃，触发熔断                       │
│  │                                                      │
│  ├── 超时（Timeout）                                    │
│  │   ├── 第 1 次重试: 等待 500ms                       │
│  │   └── 第 2 次: 放弃，标记为 TIMEOUT                 │
│  │                                                      │
│  └── 网络错误（Connection Error）                       │
│      ├── 第 1 次重试: 等待 1000ms                      │
│      └── 第 2 次: 放弃，触发熔断                       │
└─────────────────────────────────────────────────────────┘
```

### 7.4 熔断器设计

| 参数     | 值                | 说明                      |
| -------- | ----------------- | ------------------------- |
| 失败阈值 | 5 次/分钟         | 触发熔断的失败次数        |
| 熔断时长 | 30s               | 熔断后拒绝所有请求        |
| 半开探测 | 1 次/10s          | 熔断期间允许 1 次探测请求 |
| 恢复条件 | 连续 3 次探测成功 | 关闭熔断器                |

### 7.5 错误映射表

| HTTP 状态码 | 错误类型            | 处理策略         | 用户提示                               |
| ----------- | ------------------- | ---------------- | -------------------------------------- |
| 400         | PARAM_ERROR         | 不重试，返回错误 | "查询参数有误，请检查光纤编号格式"     |
| 404         | NOT_FOUND           | 不重试           | "未找到该光纤数据，请确认编号是否正确" |
| 409         | CONFLICT            | 不重试           | "数据正在更新中，请稍后重试"           |
| 429         | RATE_LIMITED        | 等待后重试       | "请求过于频繁，已自动排队"             |
| 500         | SERVER_ERROR        | 退避重试         | "服务暂时异常，正在重试..."            |
| 502/503     | SERVICE_UNAVAILABLE | 退避重试 + 熔断  | "后端服务不可用，已启用降级模式"       |
| Timeout     | TIMEOUT             | 重试 1 次        | "查询超时，正在重试..."                |

### 7.6 认证（预留）

```yaml
mcp_server:
  auth:
    enabled: false        # 当前版本不启用
    type: jwt             # 预留 JWT 认证
    header: Authorization
    prefix: Bearer
```

------

## 8. 中间件管道设计

### 8.1 执行顺序

```
请求入站 → ① AuthMiddleware → ② DomainValidationMiddleware 
         → ③ RateLimitMiddleware → ④ RAGInjectionMiddleware → Lead Agent
```

### 8.2 各中间件详细设计

#### ① AuthMiddleware（认证中间件）

| 项目     | 说明                         |
| -------- | ---------------------------- |
| 职责     | 验证用户身份，注入用户上下文 |
| 当前实现 | 单用户模式，固定 token 校验  |
| 扩展预留 | 多用户 RBAC                  |
| 失败处理 | 返回 401，不进入后续流程     |

#### ② DomainValidationMiddleware（领域校验中间件）

| 项目     | 说明                                               |
| -------- | -------------------------------------------------- |
| 职责     | 校验请求参数的领域合法性                           |
| 校验规则 | 光纤编号格式（FIB-XXXX）、时间范围合理性、批量上限 |
| 失败处理 | 返回 400 + 具体校验失败原因                        |
| 关键规则 | 批量请求 fiber_ids 数量 ≤ 200，否则拒绝            |

#### ③ RateLimitMiddleware（限流中间件）

| 项目     | 说明                      |
| -------- | ------------------------- |
| 职责     | 控制请求频率，保护后端    |
| 算法     | 令牌桶（Token Bucket）    |
| 配置     | 10 请求/分钟，突发 20     |
| 超限处理 | 返回 429 + Retry-After 头 |

#### ④ RAGInjectionMiddleware（知识注入中间件）

| 项目       | 说明                                  |
| ---------- | ------------------------------------- |
| 职责       | 请求前置阶段自动注入相关知识片段      |
| 触发条件   | 请求意图为"分析"或"报告"时触发        |
| 相似度阈值 | ≥ 0.6 才注入                          |
| 否定词过滤 | 包含"不要/不用/不需要"时排除对应类别  |
| 注入位置   | System Prompt 末尾，标记 `[知识参考]` |
| 最大注入量 | 3 条知识片段，总计 ≤ 1000 tokens      |

------

## 9. 记忆系统设计

### 9.1 短期记忆（会话级）

| 项目     | 说明                                 |
| -------- | ------------------------------------ |
| 存储位置 | 内存（进程内）                       |
| 容量     | 最近 30 条消息                       |
| 压缩策略 | > 30 条时触发 LLM 摘要压缩           |
| 压缩降级 | LLM 不可用时，直接截断最早 10 条消息 |
| 生命周期 | 会话结束后清除                       |

### 9.2 长期记忆（持久化）

| 项目     | 说明                                               |
| -------- | -------------------------------------------------- |
| 存储位置 | SQLite（单文件）                                   |
| 存储内容 | **仅关键指标快照**（非完整 JSON）                  |
| 单条大小 | < 200 字节                                         |
| 写入方式 | **异步队列**，不阻塞主响应                         |
| 去重规则 | 同一 fiber_id + 同一小时内颜色变化时保留（见 9.3） |
| 扩展预留 | 接口层抽象，可迁移至 PostgreSQL                    |

### 9.3 去重规则（修订）

> **v3.1 规则**：同一 fiber_id 同一小时内仅保留 1 条。
> **v3.2 修订**：同一 fiber_id 同一小时内，**颜色发生变化时保留**，颜色未变化则覆盖。

**理由**：简单时间窗口去重可能丢失重要状态变化。例如光纤在 1 小时内从绿色变为红色，这是关键事件，不应被去重丢弃。

```python
def should_save(new_record, existing_record):
    if existing_record is None:
        return True  # 无历史记录，保存
    if new_record.color != existing_record.color:
        return True  # 颜色变化，保存（关键事件）
    return False  # 颜色未变，覆盖（不新增）
```

### 9.4 记忆数据模型

```sql
CREATE TABLE memory_long_term (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fiber_id    TEXT NOT NULL,
    spanloss    REAL,           -- 跨段损耗值
    color       TEXT,           -- 颜色状态 (green/yellow/red)
    summary     TEXT,           -- 一句话摘要（≤100字）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 索引
    INDEX idx_fiber_time (fiber_id, created_at)
);
```

### 9.5 异步写入队列

```
analysis-expert 完成分析
        │
        ▼
┌─────────────────┐
│  异步写入队列    │  ← 非阻塞，立即返回
│  (asyncio.Queue) │
└────────┬────────┘
         │ 后台协程消费
         ▼
┌─────────────────┐
│  去重检查        │
│  (should_save)  │
└────────┬────────┘
         │ 通过
         ▼
┌─────────────────┐
│  SQLite 写入    │
└─────────────────┘
```

------

## 10. RAG 知识检索设计

### 10.1 双路径检索

| 路径     | 触发方式     | 执行者                                 | 场景            |
| -------- | ------------ | -------------------------------------- | --------------- |
| 被动注入 | 请求前置自动 | RAGInjectionMiddleware                 | 分析/报告类请求 |
| 主动检索 | 工具调用     | report-generator / knowledge-assistant | 需要规范引用时  |

### 10.2 检索参数

| 参数       | 值                 | 说明                         |
| ---------- | ------------------ | ---------------------------- |
| 相似度阈值 | 0.6                | 低于阈值不返回               |
| Top-K      | 5                  | 最多返回 5 条                |
| 最大注入   | 3 条 / 1000 tokens | 避免占用过多上下文           |
| 查询改写   | 启用               | 将用户自然语言转为检索关键词 |

### 10.3 否定词过滤

```python
NEGATION_PATTERNS = ["不要", "不用", "不需要", "别给我", "无需"]

def filter_by_negation(query: str, knowledge_items: list) -> list:
    """如果用户表达否定意图，排除对应类别知识"""
    for pattern in NEGATION_PATTERNS:
        if pattern in query:
            # 提取否定对象（如"不要规范" → 排除 category="规范"）
            exclude_category = extract_negation_target(query, pattern)
            knowledge_items = [
                item for item in knowledge_items 
                if item.category != exclude_category
            ]
    return knowledge_items
```

### 10.4 知识来源标记

每条注入的知识片段标记来源，便于溯源：

```
[知识参考 #1 | 来源: 光纤维护规范 v2.3 | 相似度: 0.82]
当光纤跨段损耗超过 15dB 时，应标记为红色并安排现场巡检...
```

------

## 11. 容错与降级设计

### 11.1 四级容错模型

```
┌─────────────────────────────────────────────────────────────┐
│  L1 正常模式                                                 │
│  所有 LLM 可用，完整智能分析                                  │
│  触发条件: 默认状态                                          │
├─────────────────────────────────────────────────────────────┤
│  L2 模型降级                                                 │
│  主模型不可用，自动切换轻量模型                               │
│  降级链: primary(7B) → fallback(3B) → fast(1.5B)            │
│  触发条件: 主模型连续 3 次超时或 5xx                         │
│  影响: 分析质量略降，功能完整                                │
├─────────────────────────────────────────────────────────────┤
│  L3 规则兜底                                                 │
│  所有 LLM 不可用，固定模板输出                               │
│  触发条件: L2 所有模型均不可用                               │
│  覆盖场景: 高频查询白名单（见 11.2）                         │
│  影响: 无智能分析，仅返回结构化数据                          │
├─────────────────────────────────────────────────────────────┤
│  L4 纯知识模式                                               │
│  后端 + LLM 均不可用，仅 RAG 知识库可访问                   │
│  触发条件: 后端 API 熔断 + LLM 全部不可用                   │
│  影响: 仅能回答知识性问题，数据查询明确拒绝                  │
│  用户提示: "数据服务暂时不可用，当前仅提供知识库查询"        │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 L3 规则兜底白名单

| 场景             | 兜底输出                      | 模板                                             |
| ---------------- | ----------------------------- | ------------------------------------------------ |
| 单条光纤性能查询 | 直接返回后端原始数据          | "光纤 {id} 当前损耗 {spanloss}dB，状态: {color}" |
| 红色光纤列表     | 返回 color=red 的光纤 ID 列表 | "当前红色光纤共 {n} 条: {id_list}"               |
| 实时统计         | 返回各颜色数量统计            | "绿色 {g} 条 / 黄色 {y} 条 / 红色 {r} 条"        |
| 告警列表         | 返回未处理告警                | "当前活跃告警 {n} 条: {alarm_list}"              |

**非白名单场景**：返回 "当前 AI 分析服务暂时不可用，请稍后重试。您仍可进行基础数据查询。"

### 11.3 四级错误分级

| 级别 | 错误类型 | 示例                  | 处理策略                     |
| ---- | -------- | --------------------- | ---------------------------- |
| E1   | 参数错误 | 光纤编号格式错误      | 立即返回，提示修正           |
| E2   | 业务错误 | 光纤不存在、数据为空  | 返回业务提示，不重试         |
| E3   | 服务错误 | 后端 5xx、超时        | 退避重试 → 熔断 → 降级       |
| E4   | 系统错误 | OOM、磁盘满、进程崩溃 | 告警 + 自动重启 + L3/L4 兜底 |

------

## 12. 数据库设计

### 12.1 SQLite 表结构

```sql
-- 长期记忆表
CREATE TABLE memory_long_term (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fiber_id    TEXT NOT NULL,
    spanloss    REAL,
    color       TEXT CHECK(color IN ('green', 'yellow', 'red')),
    summary     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_memory_fiber_time ON memory_long_term(fiber_id, created_at);

-- 会话记录表
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at    TIMESTAMP,
    message_count INTEGER DEFAULT 0
);

-- 批量任务表（游标管理）
CREATE TABLE batch_tasks (
    cursor_id       TEXT PRIMARY KEY,
    status          TEXT CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    total_count     INTEGER,
    processed_count INTEGER DEFAULT 0,
    chunk_index     INTEGER DEFAULT 0,
    total_chunks    INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP,
    result_summary  TEXT
);

-- 幂等标记表
CREATE TABLE idempotency_keys (
    chunk_id    TEXT PRIMARY KEY,
    result      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP
);

-- 操作日志表
CREATE TABLE operation_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    action      TEXT,
    sub_agent   TEXT,
    input_summary TEXT,
    output_summary TEXT,
    duration_ms INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 12.2 数据生命周期

| 表               | 保留策略     | 清理方式         |
| ---------------- | ------------ | ---------------- |
| memory_long_term | 保留 90 天   | 定时任务每日清理 |
| sessions         | 保留 30 天   | 定时任务每日清理 |
| batch_tasks      | 保留 24 小时 | 过期自动清理     |
| idempotency_keys | TTL 300s     | 过期自动清理     |
| operation_logs   | 保留 7 天    | 定时任务每日清理 |

------

## 13. 部署架构

### 13.1 服务拓扑

```
┌─────────────────────────────────────────────────────────┐
│                    单机部署（生产）                       │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Agent Service (:8080)                          │    │
│  │  ├── Lead Agent                                 │    │
│  │  ├── 4x Sub-Agent（按需实例化）                 │    │
│  │  ├── 中间件管道                                 │    │
│  │  ├── 记忆系统（SQLite）                         │    │
│  │  └── 批量处理引擎                               │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  MCP Server (:8088)                             │    │
│  │  ├── 后端 API 代理                              │    │
│  │  ├── 熔断器 + 重试                              │    │
│  │  └── 负载感知                                   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  OLLAMA Service (:11434)                        │    │
│  │  ├── primary: qwen2.5:7b                       │    │
│  │  ├── fallback: qwen2.5:3b                      │    │
│  │  └── fast: qwen2.5:1.5b                        │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  RAG Service (:8089)                            │    │
│  │  ├── 向量数据库（ChromaDB）                     │    │
│  │  └── Embedding 模型                             │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  资源需求:                                              │
│  - CPU: 8 核（LLM 推理为主）                           │
│  - 内存: 32GB（模型加载 + 推理）                       │
│  - 磁盘: 100GB（模型文件 + 知识库 + 日志）            │
│  - GPU: 可选（有 GPU 则推理加速）                      │
└─────────────────────────────────────────────────────────┘
```

### 13.2 配置管理

```yaml
# config.yaml 完整配置
app:
  name: fiber-maintenance-agent
  version: 3.2.0
  port: 8080

llm:
  provider: ollama
  base_url: http://localhost:11434
  models:
    primary: qwen2.5:7b
    fallback: qwen2.5:3b
    fast: qwen2.5:1.5b
  context_window: 8192
  default_timeout: 30s

agents:
  data_collector:
    temperature: 0.0
    top_p: 1.0
  analysis_expert:
    temperature: 0.1      # v3.2 修订
    top_p: 0.3            # v3.2 修订
    seed: 42              # 固定种子，确保可复现
  report_generator:
    temperature: 0.3
    top_p: 0.8
  knowledge_assistant:
    temperature: 0.5
    top_p: 0.9

batch:
  chunk_size: 50          # v3.2 修订
  max_total: 200
  max_chunks: 4
  chunk_timeout: 5s
  inter_chunk_delay: 200ms
  cursor_ttl: 300s

mcp_server:
  port: 8088
  timeout:
    single: 2s
    batch: 5s
    trend: 3s
    rag: 3s
  retry:
    max_attempts: 2
    backoff: [500ms, 1000ms]
    no_retry_on: [400, 404, 409]
  circuit_breaker:
    failure_threshold: 5
    window: 60s
    cooldown: 30s
  backpressure:
    error_rate_threshold: 0.10
    recovery_threshold: 0.03
    recovery_window: 60s
    throttled_concurrency: 2
    normal_concurrency: 5

memory:
  short_term:
    max_messages: 30
    compression: llm_summary
    compression_fallback: truncate_oldest_10
  long_term:
    storage: sqlite
    db_path: ./data/memory.db
    retention_days: 90
    async_write: true
    dedup_rule: color_change_within_hour

rag:
  similarity_threshold: 0.6
  top_k: 5
  max_inject: 3
  max_inject_tokens: 1000
  negation_filter: true
  query_rewrite: true

sandbox:
  enabled: false          # 设计扩展，默认关闭
  runtime: docker
  memory_limit: 512m
  cpu_limit: 0.5
  timeout: 30s
  network: disabled

rate_limit:
  algorithm: token_bucket
  rate: 10/min
  burst: 20
```

------

## 14. 测试策略

### 14.1 测试金字塔

```
         ╱╲
        ╱ E2E ╲          端到端测试（5%）
       ╱────────╲
      ╱ 集成测试  ╲       集成测试（25%）
     ╱──────────────╲
    ╱    单元测试     ╲    单元测试（70%）
   ╱────────────────────╲
```

### 14.2 单元测试

| 模块         | 测试重点                             | 覆盖率目标 |
| ------------ | ------------------------------------ | ---------- |
| 批量处理引擎 | 分块逻辑、游标管理、幂等性、部分失败 | ≥ 90%      |
| 背压控制器   | 状态机转换、阈值触发、恢复逻辑       | ≥ 90%      |
| 中间件管道   | 各中间件独立功能、顺序执行           | ≥ 85%      |
| 记忆系统     | 去重规则、异步写入、压缩降级         | ≥ 85%      |
| RAG 检索     | 阈值过滤、否定词处理、查询改写       | ≥ 80%      |
| 容错降级     | L1→L4 各级切换、白名单覆盖           | ≥ 90%      |

### 14.3 集成测试

| 场景              | 验证点                                                     |
| ----------------- | ---------------------------------------------------------- |
| 单条查询全链路    | 用户输入 → Lead Agent → data-collector → MCP → 后端 → 返回 |
| 批量查询（50条）  | 单 Chunk 处理，验证数据完整性                              |
| 批量查询（200条） | 4 Chunk 迭代，验证进度上报、聚合正确性                     |
| 批量查询部分失败  | 模拟 10% 失败率，验证重试 + 最终聚合                       |
| 背压触发          | 模拟后端 5xx > 10%，验证并发降低                           |
| 模型降级          | 停止 primary 模型，验证自动切换 fallback                   |
| L3 规则兜底       | 停止所有 LLM，验证白名单场景正常返回                       |
| 记忆去重          | 同一光纤 1 小时内多次分析，验证颜色变化保留                |

### 14.4 端到端测试

| 用例     | 输入                       | 期望输出                         |
| -------- | -------------------------- | -------------------------------- |
| 单条分析 | "分析光纤 FIB-0042 的状态" | 包含损耗值、颜色、趋势解读、建议 |
| 批量分析 | "分析 A 区所有光纤"        | 统计概览 + 异常明细 + 建议       |
| 知识问答 | "光纤损耗多少算异常？"     | 引用规范，给出阈值说明           |
| 报告生成 | "生成本周维护报告"         | 完整报告格式，含规范引用         |
| 降级场景 | 停止 LLM 后查询            | 规则兜底输出                     |

### 14.5 专项测试

| 测试类型     | 方法                         | 通过标准                         |
| ------------ | ---------------------------- | -------------------------------- |
| 确定性测试   | 同一输入执行 10 次，对比输出 | analysis-expert 输出一致率 ≥ 95% |
| 幻觉检测     | 构造无数据场景，检查是否编造 | 幻觉率 < 2%                      |
| LLM-as-Judge | 用强模型评估分析质量         | 评分 ≥ 4/5                       |
| 压力测试     | 并发 10 请求 × 200 条批量    | 无 OOM，响应 < 60s               |
| 容错演练     | 随机杀死后端/LLM 进程        | 30s 内完成降级切换               |

------

## 15. 与需求基线一致性矩阵

| 需求条目       | 需求 v3.0 描述 | 设计 v3.2 实现                       | 一致性     | 备注                           |
| -------------- | -------------- | ------------------------------------ | ---------- | ------------------------------ |
| Agent 不做计算 | 明确禁止       | 严格执行，analysis-expert 无计算工具 | ✅          | —                              |
| Sub-Agent 数量 | 5 个           | 4 个（移除 rag-retriever）           | ⚠️ 优化     | 合理精简，RAG 改为中间件+按需  |
| 工具数量       | 14 个          | 18 个（+4 批量工具）                 | ⚠️ 扩展     | 批量工程标准化所需             |
| 批量上限       | 100 条         | 200 条（分 4 块 × 50）               | ⚠️ 调整     | 总量提升，单块 50 对齐工程标准 |
| 并发策略       | 并行多实例     | 单实例分块迭代                       | ⚠️ 优化     | 资源效率提升数量级             |
| 超时设置       | 统一 5s        | 分级 2s/3s/5s                        | ⚠️ 优化     | 更精细的超时控制               |
| 记忆模型       | 完整 JSON      | 指标快照（<200B）                    | ⚠️ 优化     | 存储效率提升 10x               |
| 沙箱           | 移除           | 预留（默认关闭）                     | ⚠️ 设计扩展 | 已确认为设计扩展，不影响基线   |
| 中间件         | 4 个           | 4 个（不变）                         | ✅          | —                              |
| Skills         | 5 个           | 5 个（不变）                         | ✅          | —                              |
| RAG 配置       | 基础检索       | +阈值 0.6 +否定词 +查询改写          | ⚠️ 增强     | 向后兼容                       |
| 部署           | 单机           | 单机（+独立 MCP Server）             | ⚠️ 优化     | 故障隔离                       |
| 容错           | 二级           | 四级                                 | ⚠️ 增强     | 覆盖全故障谱                   |

------

## 16. 附录

### 附录 A：术语表

| 术语            | 说明                                         |
| --------------- | -------------------------------------------- |
| Chunk           | 分块，批量处理的最小执行单元                 |
| Cursor          | 游标，标记批量处理进度的唯一标识             |
| Backpressure    | 背压，下游处理能力不足时向上游发出的减速信号 |
| Idempotency     | 幂等性，同一操作执行多次与执行一次效果相同   |
| Circuit Breaker | 熔断器，连续失败后暂时切断请求的保护机制     |
| Token Bucket    | 令牌桶，限流算法                             |
| LLM-as-Judge    | 用 LLM 评估另一个 LLM 输出质量的方法         |

### 附录 B：主流工程标准参考

| 标准/实践              | 来源                                       | 本设计对应            |
| ---------------------- | ------------------------------------------ | --------------------- |
| 分块大小 50~100        | AWS Batch / Google Cloud Batch 最佳实践    | CHUNK_SIZE = 50       |
| 游标分页优于偏移分页   | Stripe API / GitHub API 设计规范           | cursor_id 机制        |
| 指数退避重试           | AWS Architecture Blog / gRPC 规范          | 500ms → 1000ms        |
| 熔断器模式             | Netflix Hystrix / Martin Fowler 微服务模式 | 5 次/分钟触发         |
| 背压控制               | Reactive Streams 规范 / Akka 文档          | 错误率联动并发        |
| 幂等键                 | Stripe Idempotency-Key / REST API 设计指南 | chunk_id 去重         |
| 确定性任务温度 0.1~0.3 | LLM 工程实践共识（多源）                   | analysis-expert = 0.1 |

### 附录 C：v3.1 → v3.2 变更影响分析

| 变更项       | 影响范围                         | 风险等级 | 缓解措施                            |
| ------------ | -------------------------------- | -------- | ----------------------------------- |
| 分块处理     | data-collector、批量工具、聚合层 | 中       | 充分的集成测试 + 部分失败演练       |
| 温度 0.1     | analysis-expert 输出风格         | 低       | A/B 对比测试，确认分析质量不降      |
| 沙箱定性     | 文档层面                         | 极低     | 代码中明确注释"设计扩展"            |
| 去重规则修订 | 记忆写入逻辑                     | 低       | 单元测试覆盖颜色变化/未变化两种场景 |

### 附录 D：开放问题（待后续版本解决）

| #    | 问题                       | 优先级 | 计划版本 |
| ---- | -------------------------- | ------ | -------- |
| 1    | 多用户支持（RBAC）         | 中     | v4.0     |
| 2    | PostgreSQL 迁移            | 低     | v4.0     |
| 3    | 沙箱实际启用               | 低     | 视需求   |
| 4    | 批量任务持久化（重启恢复） | 中     | v3.3     |
| 5    | 流式进度推送（WebSocket）  | 中     | v3.3     |

------

# 详细设计报告 v3.2 — 补充章节

------

## 补充说明

经对照 v3.2 现有章节，三项能力的覆盖情况如下：

| 能力项             | 现有覆盖情况                                                 | 判定             |
| ------------------ | ------------------------------------------------------------ | ---------------- |
| Agent 可观测性     | 仅在 §12 数据库设计中有 `operation_logs` 表（5 个字段），缺乏全链路追踪、Token 成本、模型参数快照、告警看板等 | ❌ **未充分覆盖** |
| Prompt 版本管理    | 全文无任何提及                                               | ❌ **完全缺失**   |
| 上下文窗口预算管理 | §4.5 聚合策略中有零散 token 估算；§10 RAG 有注入上限；但无系统性预算分配框架 | ❌ **未充分覆盖** |

以下按原文档章节格式补充三个新章节（§17、§18、§19），并同步更新配置项（§13.2）和测试策略（§14）。

------

## 17. Agent 可观测性设计

### 17.1 设计目标

> Agent 系统在生产环境中是"黑盒"——用户反馈"分析结果不对"时，必须能在 **5 分钟内** 定位到：哪个 Agent、哪次调用、什么输入、什么参数、调了哪些工具、注入了什么知识、输出了什么。

### 17.2 可观测性三支柱

```
┌─────────────────────────────────────────────────────────────────┐
│                    可观测性三支柱                                 │
│                                                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐   │
│  │   Tracing     │  │   Metrics     │  │    Logging        │   │
│  │  (链路追踪)   │  │  (指标监控)   │  │   (结构化日志)    │   │
│  │               │  │               │  │                   │   │
│  │ 全链路调用链  │  │ 延迟/吞吐/   │  │ 每次 LLM 调用    │   │
│  │ trace_id 贯穿 │  │ Token/错误率  │  │ 完整上下文快照   │   │
│  │ 跨 Agent 关联 │  │ 模型切换次数  │  │ 工具调用参数     │   │
│  └───────────────┘  └───────────────┘  └───────────────────┘   │
│                                                                 │
│  存储: 本地 SQLite（7天）+ 可选导出至 Grafana/Loki              │
└─────────────────────────────────────────────────────────────────┘
```

### 17.3 Trace 模型设计

#### 17.3.1 Trace 结构

```
Trace (一次用户请求)
├── trace_id: UUID
├── session_id: 会话 ID
├── user_id: 用户 ID
├── started_at: 起始时间
├── total_duration_ms: 总耗时
├── status: SUCCESS / DEGRADED / FAILED
│
├── Span: LeadAgent (编排)
│   ├── span_id: UUID
│   ├── intent: "batch_analysis"
│   ├── sub_agents_dispatched: ["data-collector", "analysis-expert"]
│   └── duration_ms: 12000
│
├── Span: data-collector (数据采集)
│   ├── span_id: UUID
│   ├── parent_span_id: LeadAgent.span_id
│   ├── tool_calls: [
│   │     {tool: "batch_fiber_performance_query", 
│   │      params: {chunk_id: "xxx", fiber_ids: [...]},
│   │      duration_ms: 3200, status: "success"}
│   │   ]
│   ├── model_used: "qwen2.5:7b"
│   ├── input_tokens: 850
│   ├── output_tokens: 120
│   └── duration_ms: 3500
│
├── Span: analysis-expert (分析)
│   ├── span_id: UUID
│   ├── parent_span_id: LeadAgent.span_id
│   ├── model_used: "qwen2.5:7b"
│   ├── temperature: 0.1
│   ├── top_p: 0.3
│   ├── seed: 42
│   ├── input_tokens: 3450
│   ├── output_tokens: 890
│   ├── rag_injected: [
│   │     {doc_id: "SPEC-003", similarity: 0.82, tokens: 280}
│   │   ]
│   ├── memory_read: {fiber_id: "FIB-0042", last_color: "green"}
│   ├── memory_write: {fiber_id: "FIB-0042", color: "red", async: true}
│   └── duration_ms: 5200
│
└── Span: report-generator (报告)
    ├── span_id: UUID
    ├── parent_span_id: LeadAgent.span_id
    ├── model_used: "qwen2.5:7b"
    ├── input_tokens: 2100
    ├── output_tokens: 1500
    └── duration_ms: 4800
```

#### 17.3.2 Trace 数据表

```sql
-- 链路追踪主表
CREATE TABLE traces (
    trace_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    intent          TEXT,               -- 识别出的用户意图
    status          TEXT CHECK(status IN ('SUCCESS','DEGRADED','FAILED')),
    degradation_level TEXT,             -- L1/L2/L3/L4
    total_duration_ms INTEGER,
    total_input_tokens  INTEGER,        -- 全链路输入 token 总计
    total_output_tokens INTEGER,        -- 全链路输出 token 总计
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at        TIMESTAMP
);

-- Span 明细表
CREATE TABLE spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    parent_span_id  TEXT,               -- 父 Span（树形结构）
    agent_name      TEXT NOT NULL,      -- 哪个 Sub-Agent
    span_type       TEXT,               -- 'llm_call' / 'tool_call' / 'middleware'
    
    -- LLM 调用详情
    model_used      TEXT,               -- 实际使用的模型
    temperature     REAL,               -- 温度参数快照
    top_p           REAL,               -- top_p 参数快照
    seed            INTEGER,            -- 随机种子
    input_tokens    INTEGER,            -- 输入 token 数
    output_tokens   INTEGER,            -- 输出 token 数
    prompt_hash     TEXT,               -- System Prompt 的 SHA256（关联版本）
    
    -- 工具调用详情
    tool_name       TEXT,               -- 调用的工具名
    tool_params     TEXT,               -- 工具参数（JSON，脱敏后）
    tool_status     TEXT,               -- success / timeout / error
    tool_error      TEXT,               -- 错误信息（如有）
    
    -- RAG 注入详情
    rag_docs_injected TEXT,             -- 注入的知识片段 ID 列表（JSON）
    rag_max_similarity REAL,           -- 最高相似度
    
    -- 记忆读写
    memory_read_keys  TEXT,             -- 读取的记忆 key（JSON）
    memory_write_keys TEXT,             -- 写入的记忆 key（JSON）
    
    duration_ms     INTEGER,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_span_trace (trace_id),
    INDEX idx_span_agent (agent_name, started_at)
);
```

### 17.4 Metrics 指标体系

#### 17.4.1 核心指标清单

| 指标分类       | 指标名                     | 类型      | 采集频率      | 告警阈值              |
| -------------- | -------------------------- | --------- | ------------- | --------------------- |
| **延迟**       | agent_request_duration_ms  | Histogram | 每次请求      | P95 > 30s             |
|                | llm_inference_duration_ms  | Histogram | 每次 LLM 调用 | P95 > 10s             |
|                | tool_call_duration_ms      | Histogram | 每次工具调用  | P95 > 5s              |
|                | first_token_latency_ms     | Histogram | 每次 LLM 调用 | P95 > 3s              |
| **吞吐**       | requests_per_minute        | Gauge     | 10s           | —                     |
|                | batch_chunks_per_minute    | Gauge     | 10s           | —                     |
| **Token 成本** | input_tokens_per_request   | Histogram | 每次请求      | 均值 > 5000           |
|                | output_tokens_per_request  | Histogram | 每次请求      | 均值 > 2000           |
|                | daily_total_tokens         | Counter   | 累计          | > 500K/天             |
| **错误**       | llm_error_rate             | Gauge     | 1min 窗口     | > 5%                  |
|                | tool_error_rate            | Gauge     | 1min 窗口     | > 10%                 |
|                | backend_5xx_rate           | Gauge     | 1min 窗口     | > 10%（触发背压）     |
| **降级**       | degradation_level          | Gauge     | 实时          | ≥ L2 告警             |
|                | model_fallback_count       | Counter   | 累计          | > 10/小时             |
|                | circuit_breaker_open       | Gauge     | 实时          | = 1 告警              |
| **批量**       | batch_success_rate         | Gauge     | 每次批量      | < 90%                 |
|                | batch_partial_failure_rate | Gauge     | 每次批量      | > 20%                 |
|                | chunk_retry_count          | Counter   | 累计          | > 5/小时              |
| **记忆**       | memory_write_latency_ms    | Histogram | 每次写入      | P95 > 100ms           |
|                | memory_queue_depth         | Gauge     | 10s           | > 50                  |
| **RAG**        | rag_injection_hit_rate     | Gauge     | 每次注入      | < 30%（阈值可能过高） |
|                | rag_avg_similarity         | Gauge     | 每次注入      | < 0.65                |

#### 17.4.2 指标采集实现

```python
# 装饰器模式：零侵入采集
class AgentMetrics:
    def __init__(self):
        self._counters = {}
        self._histograms = {}
    
    def trace_llm_call(self, func):
        """LLM 调用装饰器"""
        @wraps(func)
        async def wrapper(self_agent, *args, **kwargs):
            span = get_current_span()
            start = time.monotonic()
            
            try:
                result = await func(self_agent, *args, **kwargs)
                span.status = "success"
                span.output_tokens = result.usage.output_tokens
                span.input_tokens = result.usage.input_tokens
                span.model_used = result.model
                return result
            except Exception as e:
                span.status = "error"
                span.tool_error = str(e)
                self._counters['llm_errors'] += 1
                raise
            finally:
                span.duration_ms = (time.monotonic() - start) * 1000
                self._histograms['llm_duration'].observe(span.duration_ms)
        
        return wrapper
    
    def trace_tool_call(self, func):
        """工具调用装饰器"""
        @wraps(func)
        async def wrapper(self_agent, tool_name, params, *args, **kwargs):
            span = get_current_span()
            span.tool_name = tool_name
            span.tool_params = sanitize_params(params)  # 脱敏
            start = time.monotonic()
            
            try:
                result = await func(self_agent, tool_name, params, *args, **kwargs)
                span.tool_status = "success"
                return result
            except TimeoutError:
                span.tool_status = "timeout"
                raise
            except Exception as e:
                span.tool_status = "error"
                span.tool_error = str(e)
                raise
            finally:
                span.duration_ms = (time.monotonic() - start) * 1000
        
        return wrapper
```

### 17.5 Logging 结构化日志

#### 17.5.1 日志格式

```json
{
  "timestamp": "2026-07-24T16:30:00.123Z",
  "level": "INFO",
  "trace_id": "abc-123-def",
  "span_id": "span-456",
  "agent": "analysis-expert",
  "event": "llm_call_completed",
  "data": {
    "model": "qwen2.5:7b",
    "temperature": 0.1,
    "top_p": 0.3,
    "seed": 42,
    "input_tokens": 3450,
    "output_tokens": 890,
    "duration_ms": 5200,
    "prompt_version": "v3.2.1",
    "prompt_hash": "sha256:a1b2c3...",
    "rag_docs": ["SPEC-003", "GUIDE-017"],
    "memory_read": {"fiber_id": "FIB-0042"},
    "output_preview": "该光纤跨段损耗从12.1dB上升至15.2dB..."
  }
}
```

#### 17.5.2 日志级别策略

| 级别  | 记录内容                             | 保留时间           |
| ----- | ------------------------------------ | ------------------ |
| ERROR | LLM 调用失败、工具异常、降级触发     | 30 天              |
| WARN  | 重试发生、背压触发、记忆写入失败     | 14 天              |
| INFO  | 每次 LLM 调用、工具调用、批量进度    | 7 天               |
| DEBUG | 完整 Prompt 内容、完整输出、中间推理 | 3 天（仅开发环境） |

#### 17.5.3 敏感信息脱敏

```python
SENSITIVE_FIELDS = ["user_id", "fiber_ids", "raw_data"]

def sanitize_params(params: dict) -> dict:
    """工具参数脱敏：保留结构，隐藏具体值"""
    sanitized = {}
    for key, value in params.items():
        if key in SENSITIVE_FIELDS:
            if isinstance(value, list):
                sanitized[key] = f"[{len(value)} items]"
            else:
                sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized
```

### 17.6 告警与看板

#### 17.6.1 告警规则

| 告警名         | 条件                     | 级别        | 通知方式    |
| -------------- | ------------------------ | ----------- | ----------- |
| LLM 不可用     | 所有模型连续 3 次失败    | P0-Critical | 短信 + 邮件 |
| 降级至 L3      | degradation_level = L3   | P1-High     | 邮件        |
| 后端熔断       | circuit_breaker = OPEN   | P1-High     | 邮件        |
| 延迟劣化       | P95 > 30s 持续 5min      | P2-Medium   | 邮件        |
| Token 成本异常 | 日累计 > 500K tokens     | P2-Medium   | 邮件        |
| 批量失败率高   | batch_success_rate < 80% | P2-Medium   | 邮件        |
| 记忆队列积压   | memory_queue_depth > 100 | P3-Low      | 日志        |

#### 17.6.2 看板设计（Grafana）

```
┌─────────────────────────────────────────────────────────────┐
│  光纤维护 Agent 运行看板                                     │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │ 当前状态     │ │ 今日请求数   │ │ 降级级别     │          │
│  │ 🟢 L1 正常  │ │    1,247    │ │    L1       │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
│                                                             │
│  ┌──────────────────────────────────────────────────┐      │
│  │  请求延迟分布 (P50 / P95 / P99)                  │      │
│  │  ████████████░░░░░░░░░░░░  P50: 8.2s            │      │
│  │  ████████████████████░░░░  P95: 22.5s           │      │
│  │  ████████████████████████  P99: 45.1s           │      │
│  └──────────────────────────────────────────────────┘      │
│                                                             │
│  ┌────────────────────────┐ ┌────────────────────────┐     │
│  │  Token 消耗趋势        │ │  错误率 (1min 窗口)    │     │
│  │  📈 输入: 2.1M/天     │ │  LLM: 0.3%            │     │
│  │  📈 输出: 0.8M/天     │ │  工具: 1.2%           │     │
│  │  📈 总计: 2.9M/天     │ │  后端: 0.5%           │     │
│  └────────────────────────┘ └────────────────────────┘     │
│                                                             │
│  ┌──────────────────────────────────────────────────┐      │
│  │  Sub-Agent 调用分布 (今日)                        │      │
│  │  data-collector:    ████████████  523 次         │      │
│  │  analysis-expert:   ████████      312 次         │      │
│  │  report-generator:  ████          187 次         │      │
│  │  knowledge-asst:    ██             95 次         │      │
│  └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 17.7 问题排查流程（Runbook）

```
用户反馈: "FIB-0042 的分析结果不对"

Step 1: 定位 Trace
  SELECT * FROM traces 
  WHERE session_id = ? AND started_at > datetime('now', '-1 hour')
  ORDER BY started_at DESC;

Step 2: 查看 Span 链路
  SELECT * FROM spans 
  WHERE trace_id = ? 
  ORDER BY started_at;
  → 确认哪个 Agent 出了问题

Step 3: 检查 LLM 参数
  → model_used 是否为预期模型？（是否发生了降级？）
  → temperature 是否为 0.1？（是否配置被篡改？）
  → prompt_hash 是否为最新版本？（是否 Prompt 被误改？）

Step 4: 检查输入数据
  → tool_params 中 data-collector 返回了什么？
  → 后端数据是否正确？（排除数据源问题）

Step 5: 检查 RAG 注入
  → rag_docs_injected 是否注入了无关/错误知识？
  → 相似度是否过低（< 0.6 不应注入）？

Step 6: 检查记忆
  → memory_read 是否读取了过期的历史数据？
  → 是否因过期记忆误导了分析？

Step 7: 复现
  → 使用相同 input + seed=42 + 相同 prompt_version 重跑
  → 对比输出是否一致（验证确定性）
```

------

## 18. Prompt 版本管理设计

### 18.1 设计目标

> System Prompt 是 Agent 的"灵魂代码"。一个字的改动可能导致输出风格、判定标准、格式结构的全面变化。必须像管理代码一样管理 Prompt：**版本化、可回滚、可测试、可审计**。

### 18.2 Prompt 资产清单

| Prompt 资产                   | 所属 Agent             | 变更频率 | 影响范围      |
| ----------------------------- | ---------------------- | -------- | ------------- |
| lead_agent_system.md          | Lead Agent             | 低       | 全局路由逻辑  |
| data_collector_system.md      | data-collector         | 低       | 工具调用策略  |
| analysis_expert_system.md     | analysis-expert        | **中**   | 分析判定标准  |
| report_generator_system.md    | report-generator       | 中       | 报告格式/风格 |
| knowledge_assistant_system.md | knowledge-assistant    | 低       | 知识问答边界  |
| rag_injection_template.md     | RAGInjectionMiddleware | 低       | 知识注入格式  |
| l3_fallback_templates/*.md    | 规则兜底               | 低       | 降级输出      |

### 18.3 版本管理规范

#### 18.3.1 版本号规则

```
Prompt 版本号: v{major}.{minor}.{patch}

major: 角色定义/核心约束变更（如新增禁止项）
minor: 判定标准/输出格式调整（如阈值变化）
patch: 措辞优化/typo 修复（不影响语义）

示例:
  v3.2.0 → v3.2.1: 修复了一个 typo
  v3.2.1 → v3.3.0: 调整了红色光纤判定阈值描述
  v3.3.0 → v4.0.0: 新增了"禁止推荐具体厂商"约束
```

#### 18.3.2 目录结构

```
prompts/
├── VERSION                          # 当前全局版本号
├── CHANGELOG.md                     # 变更日志
├── lead_agent/
│   ├── system.md                    # 当前生效版本
│   ├── system.md.sha256            # 哈希校验
│   └── history/
│       ├── v3.0.0.md
│       ├── v3.1.0.md
│       └── v3.2.0.md
├── analysis_expert/
│   ├── system.md
│   ├── system.md.sha256
│   ├── few_shots/                   # Few-shot 示例
│   │   ├── normal_case.json
│   │   ├── anomaly_case.json
│   │   └── trend_case.json
│   └── history/
│       ├── v3.0.0.md
│       └── v3.1.0.md
├── report_generator/
│   ├── system.md
│   ├── templates/                   # 报告模板
│   │   ├── daily_report.md
│   │   ├── weekly_report.md
│   │   └── anomaly_report.md
│   └── history/
├── knowledge_assistant/
│   ├── system.md
│   └── history/
├── middleware/
│   ├── rag_injection_template.md
│   └── l3_fallback/
│       ├── single_query.md
│       ├── red_fiber_list.md
│       ├── realtime_stats.md
│       └── alarm_list.md
└── tests/                           # Prompt 回归测试
    ├── test_cases.yaml
    ├── run_regression.py
    └── results/
```

#### 18.3.3 Git 管理规范

```bash
# Prompt 变更必须走 PR 流程
git checkout -b prompt/analysis-expert-v3.3.0
# 修改 prompts/analysis_expert/system.md
# 更新 prompts/analysis_expert/system.md.sha256
# 更新 prompts/CHANGELOG.md
# 运行回归测试
python prompts/tests/run_regression.py --agent analysis_expert
# 提交 PR，需要 2 人 review
git commit -m "prompt(analysis-expert): v3.3.0 - 调整趋势判定措辞"
```

**强制规则**：

- Prompt 文件变更必须附带回归测试结果
- major 版本变更需要架构师 + 需求方双重审批
- 禁止直接在 main 分支修改 Prompt

### 18.4 Prompt 模板化设计

#### 18.4.1 变量注入机制

```markdown
<!-- prompts/analysis_expert/system.md -->
# 角色定义
你是光纤维护数据分析专家（版本: {{prompt_version}}）。

# 核心约束
- 温度参数: {{temperature}} (由系统设定，不可更改)
- 你**仅**分析 data-collector 提供的数据，禁止编造
- 所有结论必须引用具体数据字段

# 判定标准
- 红色阈值: 损耗 > {{red_threshold}} dB
- 黄色阈值: 损耗 > {{yellow_threshold}} dB
- 趋势判定: 连续 {{trend_window}} 次同方向变化视为趋势

# 输出格式
严格按以下 JSON Schema 输出:
{{output_schema}}

# 禁止事项
{{prohibitions}}
```

#### 18.4.2 变量配置

```yaml
# prompts/variables.yaml
analysis_expert:
  prompt_version: "v3.2.1"
  temperature: 0.1
  red_threshold: 15.0
  yellow_threshold: 12.0
  trend_window: 3
  output_schema: |
    {
      "fiber_id": "string",
      "status": "green|yellow|red",
      "analysis": "string (≤200字)",
      "suggestion": "string (≤100字)",
      "data_reference": "string (引用的具体字段)"
    }
  prohibitions:
    - "不得编造数据中不存在的数值"
    - "不得进行数学计算"
    - "不得推荐具体厂商或产品"
    - "不得给出超出数据支撑的结论"
```

#### 18.4.3 运行时加载

```python
class PromptManager:
    def __init__(self, prompts_dir: str):
        self.prompts_dir = prompts_dir
        self._cache = {}
    
    def load(self, agent_name: str) -> str:
        """加载 Prompt 并注入变量"""
        if agent_name in self._cache:
            return self._cache[agent_name]
        
        # 1. 读取模板
        template_path = f"{self.prompts_dir}/{agent_name}/system.md"
        template = open(template_path).read()
        
        # 2. 读取变量
        variables = self._load_variables(agent_name)
        
        # 3. 渲染
        rendered = self._render(template, variables)
        
        # 4. 计算哈希（用于 Trace 关联）
        prompt_hash = hashlib.sha256(rendered.encode()).hexdigest()
        
        # 5. 缓存
        self._cache[agent_name] = {
            "content": rendered,
            "hash": prompt_hash,
            "version": variables["prompt_version"]
        }
        
        return self._cache[agent_name]
    
    def verify_integrity(self, agent_name: str) -> bool:
        """校验 Prompt 文件是否被篡改"""
        expected_hash = open(f"{self.prompts_dir}/{agent_name}/system.md.sha256").read().strip()
        actual_hash = hashlib.sha256(
            open(f"{self.prompts_dir}/{agent_name}/system.md").read().encode()
        ).hexdigest()
        return expected_hash == actual_hash
    
    def get_version_info(self, agent_name: str) -> dict:
        """返回版本信息（用于 Trace 记录）"""
        cached = self._cache.get(agent_name)
        return {
            "version": cached["version"],
            "hash": cached["hash"],
            "loaded_at": cached.get("loaded_at")
        }
```

### 18.5 回归测试框架

#### 18.5.1 测试用例定义

```yaml
# prompts/tests/test_cases.yaml
analysis_expert:
  - id: TC-AE-001
    name: "正常光纤分析"
    input:
      fiber_data:
        fiber_id: "FIB-0001"
        spanloss: 8.5
        color: "green"
        trend: "stable"
    assertions:
      - output.status == "green"
      - "8.5" in output.analysis  # 必须引用具体数据
      - len(output.analysis) <= 200
      - no_hallucination(output, input)  # 无幻觉
    
  - id: TC-AE-002
    name: "红色光纤分析"
    input:
      fiber_data:
        fiber_id: "FIB-0042"
        spanloss: 16.2
        color: "red"
        trend: "rising"
    assertions:
      - output.status == "red"
      - "16.2" in output.analysis
      - "巡检" in output.suggestion or "检查" in output.suggestion
      - no_hallucination(output, input)
    
  - id: TC-AE-003
    name: "趋势劣化判定"
    input:
      fiber_data:
        fiber_id: "FIB-0100"
        spanloss: 13.8
        color: "yellow"
        trend: "rising"
        history: [11.2, 12.0, 12.9, 13.8]  # 连续上升
    assertions:
      - "趋势" in output.analysis or "上升" in output.analysis
      - output.status == "yellow"
    
  - id: TC-AE-004
    name: "无数据时不编造"
    input:
      fiber_data: null
    assertions:
      - output.status == "unknown" or "无法" in output.analysis
      - no_number_in_output(output)  # 不编造数值
    
  - id: TC-AE-005
    name: "确定性验证（同输入10次）"
    input:
      fiber_data:
        fiber_id: "FIB-0042"
        spanloss: 15.2
        color: "red"
        trend: "rising"
    run_count: 10
    assertions:
      - consistency_rate >= 0.95  # 10次输出一致率 ≥ 95%
```

#### 18.5.2 回归测试执行器

```python
# prompts/tests/run_regression.py
import yaml
import asyncio
from pathlib import Path

class PromptRegressionRunner:
    def __init__(self, agent_name: str, test_file: str):
        self.agent_name = agent_name
        self.test_cases = yaml.safe_load(open(test_file))[agent_name]
        self.results = []
    
    async def run_all(self):
        for tc in self.test_cases:
            result = await self._run_single(tc)
            self.results.append(result)
        
        self._print_report()
        return all(r["passed"] for r in self.results)
    
    async def _run_single(self, tc: dict) -> dict:
        run_count = tc.get("run_count", 1)
        outputs = []
        
        for i in range(run_count):
            output = await self._call_agent(tc["input"])
            outputs.append(output)
        
        # 执行断言
        passed = True
        failures = []
        for assertion in tc["assertions"]:
            if not self._evaluate(assertion, outputs, tc["input"]):
                passed = False
                failures.append(assertion)
        
        return {
            "id": tc["id"],
            "name": tc["name"],
            "passed": passed,
            "failures": failures,
            "outputs": outputs
        }
    
    def _print_report(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        print(f"\n{'='*60}")
        print(f"  Prompt 回归测试: {self.agent_name}")
        print(f"  结果: {passed}/{total} 通过")
        print(f"{'='*60}")
        for r in self.results:
            status = "✅" if r["passed"] else "❌"
            print(f"  {status} {r['id']}: {r['name']}")
            if r["failures"]:
                for f in r["failures"]:
                    print(f"      ↳ 失败: {f}")
```

#### 18.5.3 CI/CD 集成

```yaml
# .github/workflows/prompt-ci.yaml
name: Prompt Regression Test

on:
  pull_request:
    paths:
      - 'prompts/**'  # 仅 Prompt 文件变更时触发

jobs:
  regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run Prompt Regression
        run: |
          python prompts/tests/run_regression.py \
            --agent analysis_expert \
            --agent report_generator \
            --fail-on-error
      
      - name: Upload Results
        uses: actions/upload-artifact@v4
        with:
          name: prompt-test-results
          path: prompts/tests/results/
```

### 18.6 A/B 测试框架（预留）

```python
class PromptABTest:
    """Prompt A/B 测试：新 Prompt 先对 10% 流量生效"""
    
    def __init__(self, experiment_config: dict):
        self.control_version = experiment_config["control"]   # "v3.2.1"
        self.treatment_version = experiment_config["treatment"]  # "v3.3.0"
        self.traffic_ratio = experiment_config.get("ratio", 0.1)  # 10%
        self.metrics = []  # 收集评估指标
    
    def route(self, trace_id: str) -> str:
        """基于 trace_id 哈希决定走哪个版本"""
        hash_val = int(hashlib.md5(trace_id.encode()).hexdigest(), 16)
        if (hash_val % 100) < (self.traffic_ratio * 100):
            return self.treatment_version
        return self.control_version
    
    def evaluate(self):
        """对比两个版本的质量指标"""
        control_scores = [m["score"] for m in self.metrics if m["version"] == self.control_version]
        treatment_scores = [m["score"] for m in self.metrics if m["version"] == self.treatment_version]
        
        # LLM-as-Judge 评分对比
        return {
            "control_avg": sum(control_scores) / len(control_scores),
            "treatment_avg": sum(treatment_scores) / len(treatment_scores),
            "significant": t_test(control_scores, treatment_scores) < 0.05
        }
```

### 18.7 Prompt 变更审计日志

```sql
CREATE TABLE prompt_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT NOT NULL,
    old_version     TEXT,
    new_version     TEXT NOT NULL,
    change_type     TEXT CHECK(change_type IN ('major','minor','patch')),
    change_summary  TEXT,               -- 变更摘要
    changed_by      TEXT,               -- 变更人
    approved_by     TEXT,               -- 审批人
    regression_passed BOOLEAN,          -- 回归测试是否通过
    old_hash        TEXT,
    new_hash        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

------

## 19. 上下文窗口预算管理设计

### 19.1 设计目标

> 上下文窗口（8192 tokens）是 Agent 最稀缺的资源。多个组件（System Prompt、RAG 知识、历史记忆、当前数据、用户指令、输出空间）共同争抢这一有限空间。必须有**明确的预算分配、优先级排序和超限降级策略**。

### 19.2 预算分配总表

```
┌─────────────────────────────────────────────────────────────────┐
│              上下文窗口预算分配（总计 8192 tokens）                │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  固定区域（不可压缩）                    合计: 1300      │    │
│  │  ├── System Prompt:          500 tokens  (6.1%)        │    │
│  │  ├── 用户当前指令:           300 tokens  (3.7%)        │    │
│  │  └── 输出格式约束:           500 tokens  (6.1%)        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  弹性区域（可压缩/可裁剪）               合计: 4892      │    │
│  │  ├── 当前数据:            3000 tokens  (36.6%)  [P1]   │    │
│  │  ├── RAG 知识注入:        1000 tokens  (12.2%)  [P2]   │    │
│  │  ├── 历史记忆:             500 tokens  (6.1%)   [P3]   │    │
│  │  └── 安全余量:             392 tokens  (4.8%)          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  输出预留区域（不可侵占）                合计: 2000      │    │
│  │  └── LLM 输出空间:        2000 tokens  (24.4%)        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  优先级: P1(数据) > P2(知识) > P3(记忆)                         │
│  原则: 输出预留不可侵占；固定区域不可压缩；弹性区域按优先级裁剪  │
└─────────────────────────────────────────────────────────────────┘
```

### 19.3 各区域预算细则

#### 19.3.1 System Prompt（500 tokens，固定）

| 组成部分 | Token 预算 | 说明                           |
| -------- | ---------- | ------------------------------ |
| 角色定义 | 80         | "你是光纤维护数据分析专家"     |
| 核心约束 | 150        | 禁止事项（不做计算、不编造等） |
| 判定标准 | 120        | 阈值、趋势规则                 |
| 输出格式 | 100        | JSON Schema 简述               |
| 版本标记 | 50         | prompt_version + hash          |

**压缩策略**：System Prompt 为固定区域，**不允许压缩**。如果 Prompt 迭代导致超出 500 tokens，必须精简措辞而非扩大预算。

#### 19.3.2 当前数据（3000 tokens，P1 优先级）

| 场景            | 数据量 | Token 估算 | 处理策略                 |
| --------------- | ------ | ---------- | ------------------------ |
| 单条查询        | 1 条   | ~150       | 全量传入                 |
| 批量（≤10条）   | 10 条  | ~1500      | 全量传入                 |
| 批量（11~50条） | 50 条  | 超限       | **聚合策略**（见 19.4）  |
| 批量（>50条）   | 200 条 | 严重超限   | **分块 + 聚合**（见 §4） |

#### 19.3.3 RAG 知识注入（1000 tokens，P2 优先级）

| 配置            | 值    | 说明                   |
| --------------- | ----- | ---------------------- |
| 最大注入条数    | 3     | 硬性上限               |
| 单条最大 tokens | 350   | 超出则截断             |
| 总预算          | 1000  | 3 × 350 = 1050，留余量 |
| 相似度阈值      | ≥ 0.6 | 低于不注入             |

**压缩策略**：

```
if total_rag_tokens > 1000:
    # 策略 1: 减少条数（3 → 2 → 1）
    # 策略 2: 截断每条至 250 tokens
    # 策略 3: 仅保留最相关的 1 条
```

#### 19.3.4 历史记忆（500 tokens，P3 优先级）

| 配置            | 值   | 说明                  |
| --------------- | ---- | --------------------- |
| 最大记忆条数    | 3    | 最近 3 条相关记忆     |
| 单条最大 tokens | 150  | 仅指标快照 + 摘要     |
| 总预算          | 500  | 3 × 150 = 450，留余量 |

**压缩策略**：

```
if total_memory_tokens > 500:
    # 策略 1: 减少条数（3 → 2 → 1）
    # 策略 2: 仅保留最近 1 条
    # 策略 3: 完全不注入（记忆为可选增强）
```

#### 19.3.5 输出预留（2000 tokens，不可侵占）

| 输出类型     | 预估 tokens | 说明              |
| ------------ | ----------- | ----------------- |
| 单条分析结论 | 300~500     | JSON 格式         |
| 批量统计摘要 | 800~1200    | 含 Top-N 明细     |
| 完整报告     | 1500~2000   | 含建议 + 规范引用 |

**硬性规则**：无论输入如何膨胀，输出预留 2000 tokens **绝不让渡**。输入超限时压缩输入，而非压缩输出空间。

### 19.4 数据聚合策略（解决批量超限）

```python
class ContextBudgetManager:
    """上下文预算管理器"""
    
    BUDGET = {
        "system_prompt": 500,      # 固定
        "user_instruction": 300,   # 固定
        "output_format": 500,      # 固定
        "data": 3000,              # P1 弹性
        "rag": 1000,               # P2 弹性
        "memory": 500,             # P3 弹性
        "output_reserve": 2000,    # 固定（不可侵占）
        "safety_margin": 392,      # 固定
    }
    TOTAL = 8192
    
    def allocate(self, data_tokens: int, rag_tokens: int, memory_tokens: int) -> dict:
        """动态分配预算"""
        fixed = (self.BUDGET["system_prompt"] + 
                 self.BUDGET["user_instruction"] + 
                 self.BUDGET["output_format"] + 
                 self.BUDGET["output_reserve"] + 
                 self.BUDGET["safety_margin"])
        
        available_for_flex = self.TOTAL - fixed  # = 4500
        
        # 按优先级分配
        allocation = {}
        remaining = available_for_flex
        
        # P1: 数据（最高优先级）
        allocation["data"] = min(data_tokens, self.BUDGET["data"], remaining)
        remaining -= allocation["data"]
        
        # P2: RAG
        allocation["rag"] = min(rag_tokens, self.BUDGET["rag"], remaining)
        remaining -= allocation["rag"]
        
        # P3: 记忆（最低优先级）
        allocation["memory"] = min(memory_tokens, self.BUDGET["memory"], remaining)
        
        return allocation
    
    def compress_if_needed(self, data_items: list, budget: int) -> dict:
        """数据超预算时的聚合策略"""
        raw_tokens = self._estimate_tokens(data_items)
        
        if raw_tokens <= budget:
            # 未超限：全量传入
            return {"mode": "full", "data": data_items, "tokens": raw_tokens}
        
        # 超限：执行聚合
        stats = self._compute_statistics(data_items)  # 程序化统计，不经 LLM
        anomalies = self._extract_top_anomalies(data_items, top_n=10)
        
        stats_tokens = self._estimate_tokens(stats)      # ~500 tokens
        anomaly_tokens = self._estimate_tokens(anomalies)  # ~2000 tokens
        
        if stats_tokens + anomaly_tokens <= budget:
            return {
                "mode": "aggregated",
                "statistics": stats,
                "top_anomalies": anomalies,
                "total_count": len(data_items),
                "tokens": stats_tokens + anomaly_tokens
            }
        
        # 仍然超限：进一步压缩
        top5 = anomalies[:5]
        return {
            "mode": "minimal",
            "statistics": stats,
            "top_anomalies": top5,
            "total_count": len(data_items),
            "note": f"仅展示 Top-5 异常（共 {len(data_items)} 条）",
            "tokens": stats_tokens + self._estimate_tokens(top5)
        }
    
    def _compute_statistics(self, items: list) -> dict:
        """程序化统计（不经过 LLM，零 token 消耗）"""
        return {
            "total": len(items),
            "green_count": sum(1 for i in items if i["color"] == "green"),
            "yellow_count": sum(1 for i in items if i["color"] == "yellow"),
            "red_count": sum(1 for i in items if i["color"] == "red"),
            "avg_spanloss": round(sum(i["spanloss"] for i in items) / len(items), 2),
            "max_spanloss": max(i["spanloss"] for i in items),
            "min_spanloss": min(i["spanloss"] for i in items),
        }
    
    def _extract_top_anomalies(self, items: list, top_n: int) -> list:
        """提取 Top-N 异常（按损耗降序）"""
        sorted_items = sorted(items, key=lambda x: x["spanloss"], reverse=True)
        return sorted_items[:top_n]
```

### 19.5 超限降级决策树

```
┌─────────────────────────────────────────────────────────────────┐
│                    上下文超限降级决策树                            │
│                                                                 │
│  计算总需求 = data + rag + memory + fixed                       │
│                                                                 │
│  总需求 ≤ 8192?                                                 │
│  ├── YES → 正常执行                                             │
│  │                                                              │
│  └── NO → 超预算，启动降级                                      │
│       │                                                         │
│       ├── Step 1: 压缩 P3（记忆）                               │
│       │   ├── 3条 → 1条 → 0条                                  │
│       │   └── 压缩后 ≤ 8192? → YES → 执行                      │
│       │                                                         │
│       ├── Step 2: 压缩 P2（RAG）                                │
│       │   ├── 3条 → 2条 → 1条 → 0条                            │
│       │   └── 压缩后 ≤ 8192? → YES → 执行                      │
│       │                                                         │
│       ├── Step 3: 压缩 P1（数据）                               │
│       │   ├── 全量 → 聚合（统计+Top10）→ 最小（统计+Top5）     │
│       │   └── 压缩后 ≤ 8192? → YES → 执行                      │
│       │                                                         │
│       └── Step 4: 仍然超限（极端情况）                          │
│           ├── 拒绝执行，返回错误                                 │
│           └── "数据量过大，请缩小查询范围（建议 ≤ 50 条）"       │
│                                                                 │
│  ⚠️ 绝对红线:                                                   │
│  - output_reserve (2000) 永不让渡                               │
│  - system_prompt (500) 永不压缩                                 │
│  - 宁可丢弃 RAG/记忆，也不压缩数据（数据是分析基础）            │
└─────────────────────────────────────────────────────────────────┘
```

### 19.6 各 Sub-Agent 预算配置

| Sub-Agent           | 数据预算 | RAG 预算 | 记忆预算 | 输出预留 | 说明                               |
| ------------------- | -------- | -------- | -------- | -------- | ---------------------------------- |
| data-collector      | 500      | 0        | 0        | 500      | 主要做工具调用，不需要大数据上下文 |
| **analysis-expert** | **3000** | **0**    | **500**  | **2000** | 数据为主，不需要 RAG               |
| report-generator    | 1000     | 1000     | 300      | 2000     | 需要 RAG 规范引用                  |
| knowledge-assistant | 0        | 1500     | 200      | 2000     | 以 RAG 知识为主                    |

> **关键设计**：analysis-expert 不分配 RAG 预算（知识由 RAGInjectionMiddleware 前置注入到 System Prompt 中，不占用数据区域）。report-generator 的 RAG 预算最大（需要规范引用来生成报告）。

### 19.7 Token 估算工具

```python
class TokenEstimator:
    """轻量级 Token 估算（不依赖 tiktoken，避免额外依赖）"""
    
    # 中文: 约 1.5 字/token; 英文: 约 4 字符/token; JSON: 约 3 字符/token
    RATIOS = {
        "chinese": 1.5,    # 字符/token
        "english": 4.0,
        "json": 3.0,
        "code": 3.5,
    }
    
    def estimate(self, text: str, content_type: str = "json") -> int:
        """估算 token 数"""
        ratio = self.RATIOS.get(content_type, 3.0)
        return int(len(text) / ratio) + 10  # +10 安全余量
    
    def estimate_json(self, data: dict) -> int:
        """估算 JSON 对象的 token 数"""
        json_str = json.dumps(data, ensure_ascii=False)
        return self.estimate(json_str, "json")
    
    def estimate_list(self, items: list) -> int:
        """估算列表的 token 数"""
        return sum(self.estimate_json(item) for item in items)
    
    def check_budget(self, components: dict, total_budget: int = 8192) -> dict:
        """检查预算是否超限"""
        total_used = sum(components.values())
        return {
            "total_budget": total_budget,
            "total_used": total_used,
            "remaining": total_budget - total_used,
            "over_budget": total_used > total_budget,
            "utilization": f"{total_used/total_budget*100:.1f}%"
        }
```

### 19.8 运行时预算监控

```python
# 每次 LLM 调用前，记录预算使用情况
async def call_llm_with_budget_check(agent, messages, budget_config):
    # 1. 估算各组件 token
    estimator = TokenEstimator()
    components = {
        "system_prompt": estimator.estimate(messages["system"]),
        "data": estimator.estimate(messages.get("data", "")),
        "rag": estimator.estimate(messages.get("rag_context", "")),
        "memory": estimator.estimate(messages.get("memory_context", "")),
        "user_msg": estimator.estimate(messages["user"]),
    }
    
    # 2. 检查预算
    budget_mgr = ContextBudgetManager()
    check = estimator.check_budget(components)
    
    if check["over_budget"]:
        # 3. 触发压缩
        messages = budget_mgr.compress(messages, budget_config)
        # 重新估算
        components = budget_mgr.recalculate(messages)
    
    # 4. 记录到 Span（可观测性）
    span = get_current_span()
    span.budget_snapshot = {
        "components": components,
        "total_used": sum(components.values()),
        "compression_applied": check["over_budget"],
        "utilization": f"{sum(components.values())/8192*100:.1f}%"
    }
    
    # 5. 执行 LLM 调用
    return await agent.llm.call(messages)
```

### 19.9 预算告警指标

| 指标                     | 告警条件              | 说明                              |
| ------------------------ | --------------------- | --------------------------------- |
| context_utilization      | > 90% 持续 10 次      | 接近窗口上限，可能需要优化 Prompt |
| compression_trigger_rate | > 30% 请求触发压缩    | 预算分配不合理，需调整            |
| rag_dropped_rate         | > 20% 请求 RAG 被裁剪 | RAG 预算不足或注入过多            |
| memory_dropped_rate      | > 40% 请求记忆被裁剪  | 可接受（记忆为可选增强）          |
| data_truncated_rate      | > 5% 请求数据被截断   | 严重问题，需检查批量策略          |

------

## 20. 配置项补充（§13.2 增量）

以下配置项追加至 `config.yaml`：

```yaml
# ===== §17 可观测性配置 =====
observability:
  tracing:
    enabled: true
    storage: sqlite              # traces + spans 表
    retention_days: 7
    sample_rate: 1.0             # 单用户场景全量采样
  metrics:
    enabled: true
    export_interval: 60s         # 指标聚合间隔
    export_target: null          # 预留: prometheus / grafana
  logging:
    level: INFO                  # 生产: INFO; 开发: DEBUG
    format: json                 # 结构化日志
    retention_days: 7
    sensitive_fields:            # 脱敏字段
      - user_id
      - fiber_ids
      - raw_data
  alerts:
    enabled: true
    channels:
      - type: email
        recipients: ["ops@company.com"]
      - type: webhook            # 预留
        url: null
    rules:
      - name: llm_unavailable
        condition: "all_models_failed >= 3"
        level: P0
      - name: degradation_l3
        condition: "degradation_level == 'L3'"
        level: P1
      - name: high_latency
        condition: "p95_latency_ms > 30000 for 5m"
        level: P2

# ===== §18 Prompt 版本管理配置 =====
prompt_management:
  prompts_dir: ./prompts
  integrity_check: true          # 启动时校验 Prompt 哈希
  hot_reload: false              # 是否支持热更新（生产建议 false）
  regression:
    enabled: true
    test_file: ./prompts/tests/test_cases.yaml
    fail_on_error: true          # 回归失败则阻止启动
  ab_test:
    enabled: false               # 预留
    default_ratio: 0.1

# ===== §19 上下文预算配置 =====
context_budget:
  total_window: 8192
  allocation:
    system_prompt: 500           # 固定
    user_instruction: 300        # 固定
    output_format: 500           # 固定
    output_reserve: 2000         # 固定（不可侵占）
    safety_margin: 392           # 固定
    # 弹性区域（按 Agent 差异化配置）
  per_agent:
    data_collector:
      data: 500
      rag: 0
      memory: 0
    analysis_expert:
      data: 3000
      rag: 0
      memory: 500
    report_generator:
      data: 1000
      rag: 1000
      memory: 300
    knowledge_assistant:
      data: 0
      rag: 1500
      memory: 200
  compression:
    strategy: priority_based     # 按 P1>P2>P3 优先级裁剪
    data_aggregation:
      top_n_anomalies: 10        # 聚合时保留 Top-N 异常
      min_top_n: 5               # 最小保留数
    rag_fallback:
      max_items: 3
      min_items: 1
    memory_fallback:
      max_items: 3
      min_items: 0               # 记忆可完全丢弃
  monitoring:
    alert_utilization_threshold: 0.90
    alert_compression_rate: 0.30
```

------

## 21. 测试策略补充（§14 增量）

### 21.1 可观测性测试

| 测试项       | 验证点                           | 通过标准             |
| ------------ | -------------------------------- | -------------------- |
| Trace 完整性 | 每次请求生成完整 Trace + Span 链 | 100% 请求有 trace_id |
| Span 关联    | parent_span_id 正确关联          | 树形结构无断链       |
| Token 统计   | input/output tokens 与实际一致   | 误差 < 5%            |
| 脱敏验证     | 日志中无原始 fiber_ids           | 正则扫描零命中       |
| 告警触发     | 模拟 LLM 全挂，验证 P0 告警      | 30s 内触发           |
| 看板数据     | Grafana 面板数据与 DB 一致       | 抽样对比零偏差       |

### 21.2 Prompt 版本管理测试

| 测试项     | 验证点                        | 通过标准            |
| ---------- | ----------------------------- | ------------------- |
| 哈希校验   | 篡改 Prompt 文件后启动        | 启动失败 + 明确报错 |
| 版本加载   | 切换版本号后 Agent 行为变化   | 输出符合新版本预期  |
| 回归测试   | 修改 Prompt 后跑 5 个标准用例 | 全部通过            |
| 确定性     | 同版本同输入跑 10 次          | 一致率 ≥ 95%        |
| 热更新拒绝 | hot_reload=false 时修改文件   | 不生效，需重启      |
| 审计日志   | 每次变更记录完整              | 表中有对应记录      |

### 21.3 上下文预算测试

| 测试项      | 验证点                          | 通过标准                    |
| ----------- | ------------------------------- | --------------------------- |
| 单条查询    | 预算利用率 < 50%                | 无压缩触发                  |
| 批量 50 条  | 聚合策略生效                    | 数据区域 ≤ 3000 tokens      |
| 批量 200 条 | 分块 + 聚合                     | 每块 LLM 输入 ≤ 4500 tokens |
| RAG 超限    | 注入 5 条知识（超 1000 tokens） | 自动裁剪至 3 条             |
| 记忆超限    | 注入 10 条记忆                  | 自动裁剪至 3 条             |
| 极端超限    | 所有区域同时超限                | 按 P3→P2→P1 顺序裁剪        |
| 输出预留    | 输入占满 6192 tokens            | 输出仍有 2000 tokens 空间   |
| 预算监控    | 记录 utilization 到 Span        | 每次调用有 budget_snapshot  |

------

## 22. 更新后的一致性矩阵（§15 增量）

| 新增能力               | 需求基线关联        | 设计定位 | 说明                      |
| ---------------------- | ------------------- | -------- | ------------------------- |
| 可观测性（§17）        | 非功能需求-可维护性 | 核心设计 | 生产运维必备              |
| Prompt 版本管理（§18） | 非功能需求-可维护性 | 核心设计 | Agent 系统的"代码管理"    |
| 上下文预算管理（§19）  | 性能需求-响应时间   | 核心设计 | 8K 窗口硬约束下的资源调度 |

------



## 文档审批

| 角色       | 姓名 | 签字 | 日期 |
| ---------- | ---- | ---- | ---- |
| 架构师     |      |      |      |
| 技术负责人 |      |      |      |
| 需求方代表 |      |      |      |
| 测试负责人 |      |      |      |

------

*— 文档结束 —*