# Fiber Maintenance Agent (LangGraph) — Agent Instructions

光纤维护智能体系统 v7.1-Final，基于 LangChain + LangGraph 构建的多节点编排 Agent。
后端通过 REST API 与 C++ 光纤维护服务通信，前端为 Vue 3 + TypeScript 管理界面。

## Module Boundaries

```
src/
├── graph/           # 主编排图（StateGraph 定义、路由逻辑、状态模型）
│   ├── main_graph.py   # 18 节点主图构建入口
│   ├── routing.py      # 条件路由函数
│   ├── state.py        # MainGraphState + Pydantic 结构化输出模型
│   └── subgraphs/      # 子图：data_collector（唯一绑定后端 Tool）、knowledge_assistant、proactive
├── nodes/           # 各节点实现（每文件一个节点函数）
│   ├── input_guard → rule_engine → fast_path / param_gate / intent_classifier
│   ├── intent_router → rule_judgment → analysis_expert
│   ├── narrator → narrator_validator → template_fallback
│   └── report_generator → report_evaluator → result_aggregator → degradation_handler
├── tools/           # 23+ REST Tool（按领域分文件），通过 _http_client.py 统一调用后端
│   ├── DATA_COLLECTOR_TOOLS  — 拓扑/性能/告警/着色/统计/板卡/网元
│   ├── REPORT_TOOLS          — RAG + 导出（PDF/Excel/CSV）
│   ├── KNOWLEDGE_TOOLS       — RAG 检索 + 记忆查询
│   └── PULLCALL_TOOLS        — 点名流程（需确认）
├── llm/             # 三层 LLM 梯度配置（14b/7b/3b）+ 提示词加载
├── rag/             # RAG 引擎：ChromaDB + BM25 混合检索、文档摄入、查询改写
├── cache/           # 本地 SQLite 缓存层
├── events/          # 事件监听与路由（WebSocket 推送）
├── observability/   # Prometheus 指标、审计日志、链路追踪
├── resilience/      # 降级管理 + 健康探针
├── security/        # 输出过滤
├── export/          # PDF/Excel/CSV 导出实现
├── config.py        # 全局配置（环境变量 + .env）
├── server.py        # FastAPI 应用入口（/fiber-agent/invoke, /stream, /health, /metrics）
└── frontend_api.py  # 前端专用 API 路由

frontend/            # Vue 3 + TypeScript + Vite + Naive UI
├── src/api/            # API 客户端层（REST + SSE + WebSocket）
├── src/stores/         # Pinia 状态管理（chat, threads, workflow, knowledge, monitor）
├── src/views/          # 页面组件
└── src/composables/    # 组合式函数（ECharts, 轮询, 主题）

prompts/             # 提示词管理（Markdown 模板 + few-shot JSON）
├── analysis_expert/    # 分析专家 system prompt + few_shots
├── data_collector/     # 数据采集器 system prompt
├── knowledge_assistant/# 知识助手 system prompt
├── lead_agent/         # 意图分类、任务分解、结果聚合 prompt
├── report_generator/   # 报告生成 prompt + 模板（daily_report, fault_report）
└── tests/              # 提示词回归测试（run_regression.py + test_cases.yaml）

tests/               # pytest 测试（unit / integration / e2e）
```

## Commands

| 用途 | 命令 |
|------|------|
| 安装依赖 | `make install` |
| 启动后端（开发） | `make dev` |
| 启动前端（开发） | `make frontend-dev` |
| 全量启动 | `make start-all` |
| 运行全部测试 | `make test` |
| 单元测试 | `make test-unit` |
| 集成测试 | `make test-integration` |
| Lint 检查 | `make lint` |
| 自动格式化 | `make format` |
| Docker 构建/启动 | `make docker-build && make docker-up` |
| 知识库摄入 | `make ingest-kb` |
| 清理缓存 | `make clean` |

## Validation Route

变更后必须执行的最小验证：

```bash
make test-unit     # 快速单元测试
make lint          # ruff check + format check
```

完整验证（提交前）：

```bash
make test          # pytest 全量 + coverage
cd frontend && npm run type-check && npm run test:run
```

提示词变更后运行回归：

```bash
python prompts/tests/run_regression.py
```

## Key Constraints

- **Python >= 3.11**，虚拟环境通过 `pip install -e ".[dev]"` 安装
- **LangGraph StateGraph 架构**：主图 18 节点 + 4 终止保护（轮次≤3、LLM 预算≤10、无进展检测、工具全失败熔断）
- **三层 LLM 梯度**：Heavy(14b) 用于分析/报告，Medium(7b) 用于意图分类，Light(3b) 用于快速路径；通过 Ollama 本地部署
- **prompts/ 目录为提示词唯一管理点**：修改提示词必须编辑对应 .md 文件，不得硬编码在 Python 中
- **Tool 层仅通过 `_http_client.py` 访问后端**：所有 REST 调用经过熔断器 + 超时 + 重试
- **状态模型使用 Pydantic + TypedDict**：`NormalizedParams` 严格对齐 C++ 后端 int32/enum 类型
- **环境变量通过 `.env` 配置**：参考 `.env.example`
