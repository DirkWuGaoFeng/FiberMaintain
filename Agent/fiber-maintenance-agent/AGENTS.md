# Fiber Maintenance Agent (v3.2.1) — Agent Instructions

基于 LLM + RAG + MCP 架构的光纤网络智能运维助手，Python 3.11+ / FastAPI。
通过 MCP（gRPC-HTTP 网关）调用 C++ 后端微服务，支持 SSE 流式对话、批量处理、报告导出。

## Module Boundaries

```
src/
├── main.py                # FastAPI 入口（SSE/WebSocket/REST/健康检查/Prometheus）
├── settings.py            # 配置加载（config.yaml + ${ENV:default} 环境变量插值）
├── agents/
│   ├── lead_agent.py         # Lead Agent 编排器（意图识别 → task 派遣 → 结果汇总）
│   ├── sub_agents.py         # 5 个 Sub-Agent 定义（拓扑/数据/分析/报告/知识）
│   ├── llm.py                # LLM 调用层（多模型降级切换、熔断器）
│   ├── batch_engine.py       # 批量处理引擎（分片 + 游标 + 背压 + 幂等）
│   ├── fallback.py           # 四级容错（LLM 降级 → Prompt 降级 → 缓存 → 兜底）
│   ├── prompt_manager.py     # Prompt 版本管理 + A/B 测试 + 审计
│   ├── context_budget.py     # 上下文 Token 预算控制（优先级裁剪）
│   └── scheduler.py          # Sub-Agent 调度器
├── mcp/
│   └── fiber_backend.py      # MCP 工具连接器（gRPC-HTTP 网关客户端）
├── middlewares/               # 中间件链（按顺序执行）
│   ├── base.py               # Middleware 基类 + MiddlewareChain
│   ├── rate_limit.py         # 令牌桶限流（10/min）
│   ├── model_degradation.py  # 模型降级中间件
│   ├── domain_validation.py  # 领域校验（意图预分类 + 参数自纠正）
│   ├── rag_injection.py      # RAG 注入（输入清洗 + Prompt 注入防护）
│   ├── output_verification.py# 输出自检 + 数据一致性校验
│   └── audit_log.py          # 审计日志
├── rag/
│   ├── engine.py             # RAG 混合检索引擎（ChromaDB 向量 + BM25）
│   └── ingest.py             # 知识库文档导入（6 类目录 → collection）
├── memory/
│   └── store.py              # 短期 + 长期记忆存储（SQLite）
├── monitoring/
│   ├── observability.py      # Trace（SQLite 7d）+ Metrics（60s 聚合）+ 结构化日志
│   └── metrics.py            # Prometheus 指标定义
├── tools/
│   ├── registry.py           # Tool 注册器（装饰器自动构建 OpenAI function schema）
│   ├── topology_tools.py     # 拓扑查询工具
│   ├── performance_tools.py  # 性能查询工具
│   ├── alarm_tools.py        # 告警查询工具
│   ├── colored_tools.py      # 着色查询工具
│   ├── stats_tools.py        # 统计查询工具
│   ├── rag_tools.py          # RAG 检索工具
│   ├── memory_tools.py       # 记忆查询工具
│   └── export_tools.py       # 报告导出工具（PDF/Excel）
├── notify/
│   └── notifier.py           # 企微/邮件通知
├── export/
│   └── exporters.py          # PDF/Excel 报告导出实现
└── plugins/
    └── sdk.py                # 插件 SDK + 热加载

frontend/                  # Vue 3 前端（Vite 构建）
knowledge_base/            # 知识库文档（6 类目录：设备手册/维护规范/告警指南/故障案例/衰耗标准/网元配置）
skills/                    # Agent 技能定义（Markdown 格式）
config.yaml                # 配置中心（YAML + 环境变量插值）
docker-compose.yaml        # 全栈部署（Ollama + ChromaDB + Backend + Agent + Frontend + Prometheus + Grafana）
.gitlab-ci.yml             # CI/CD（test → build → deploy）
```

## Commands

| 用途 | 命令 |
|------|------|
| 安装依赖 | `make install` 或 `pip install -r requirements.txt` |
| 启动（开发） | `make dev` 或 `uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload` |
| Windows 一键启动 | `start_agent.bat` |
| 运行测试 | `make test` 或 `pytest tests/ -v --html=tests/reports/report.html` |
| 重建知识库索引 | `make ingest` 或 `python -m src.rag.ingest --rebuild` |
| API 测试报告 | `make report` 或 `python tests/test_client.py --all --report` |
| Docker 部署 | `make up` 或 `docker compose up -d --build` |
| Docker 停止 | `make down` |
| 前端开发 | `cd frontend && npm install && npm run dev` |

## Validation Route

变更后必须执行的最小验证：

```bash
pytest tests/test_batch_engine.py tests/test_context_budget.py -v
```

完整验证（提交前）：

```bash
make test                                    # pytest 全量
python tests/test_client.py --all --report   # API 集成测试
```

CI 流水线（GitLab）：

```yaml
test → build → deploy    # test 阶段失败则 build/deploy 不执行
```

## Key Constraints

- **Python >= 3.11**，依赖在 `requirements.txt` 中管理
- **config.yaml 为配置唯一管理点**：所有配置通过 `config.yaml` + `${ENV:default}` 环境变量插值，由 `src/settings.py` 的 `Settings` 类加载；修改配置必须编辑 `config.yaml`，不得硬编码
- **LLM 多模型降级**：primary(7b) → fallback(3b) → fast(3b)；连续失败 3 次触发熔断，60s 后半开恢复；provider 支持 `ollama` 和 `openai_compatible`
- **中间件链顺序固定**：RateLimit → ModelDegradation → DomainValidation → RAGInjection → OutputVerification → AuditLog；新增中间件必须插入正确位置
- **Tool 装饰器注册**：所有工具通过 `@tool()` 装饰器注册到 `src/tools/registry.py` 的全局 `_REGISTRY`；插件通过 `register_tool_object()` 注入
- **fiber_id 必须为纯数字**：后端 API 的 fiber_id 是 int32 类型，Agent 层必须从用户输入中提取数字部分
- **RAG 混合检索**：ChromaDB 向量（权重 0.6）+ BM25（权重 0.4），最终 top_k=3；知识库文档在 `knowledge_base/` 下按 6 类目录组织
- **批量引擎约束**：分片大小 50、游标 TTL 300s、背压控制（高阈值 0.10 / 低阈值 0.03）、批量上限 200
- **上下文预算**：总 8192 tokens，固定开销 1300，输出预留 2000，数据优先级 P1=3000 > P2(RAG)=1000 > P3(记忆)=500
- **后端连接**：通过 `src/mcp/fiber_backend.py` 连接 API Gateway（默认 `http://localhost:8080`），超时 5s，最多重试 2 次
- **Docker Compose 全栈**：包含 Ollama（GPU）、ChromaDB、fiber-backend、Agent、Frontend、Prometheus、Grafana 共 7 个服务
- **日志命名空间**：所有日志使用 `fiber.*` 命名空间（如 `fiber.main`、`fiber.lead`、`fiber.tool`），避免与 uvicorn root logger 冲突
