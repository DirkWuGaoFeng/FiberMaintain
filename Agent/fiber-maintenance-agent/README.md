# 光纤维护智能 Agent (Fiber Maintenance Agent)

基于 LLM + RAG + MCP 架构的下一代光纤网络智能运维助手，版本 v3.2.1。

## 核心能力

- **智能对话**：自然语言交互，自动解析运维意图，调度 Sub-Agent 协同处理
- **5 个 Sub-Agent**：拓扑分析、数据采集、分析专家、报告生成、知识助手
- **RAG 知识检索**：向量 (ChromaDB) + BM25 混合检索，Ollama 本地 Embedding (nomic-embed-text)
- **MCP 工具调用**：通过 gRPC-HTTP 网关调用后端微服务，获取实时网络数据
- **批量处理引擎**：分片 + 游标 + 背压控制 + 幂等保证
- **四级容错**：LLM 降级 → Prompt 降级 → 缓存 → 兜底回复
- **可观测性**：Trace (SQLite 7d) + Metrics (60s 聚合) + 结构化日志
- **Prompt 管理**：版本控制 + A/B 测试 + 审计日志
- **上下文预算**：Token 估算 + 动态分配 + 优先级裁剪
- **报告导出**：PDF / Excel 格式，24h 自动清理
- **插件系统**：工具/Agent 插件热加载

## 快速开始

### Windows 一键启动

```bat
start_agent.bat
```

脚本自动完成：检查 Python → 创建虚拟环境 → 激活 → 安装依赖 → 启动服务 (:8000)

### 手动启动

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux

# 安装依赖
pip install -r requirements.txt

# 开发模式启动
make dev
# 或
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端页面：

| 路径 | 页面 |
|------|------|
| `/` | 主视图（对话 + 拓扑） |
| `/dashboard` | 数据看板 |
| `/chat` | 对话界面 |
| `/admin/knowledge` | 知识库管理 |
| `/observability` | 运行看板（Trace/Metrics/Token） |

## 项目结构

```
fiber-maintenance-agent/
├── src/
│   ├── main.py              # FastAPI 入口 (SSE/WebSocket/REST)
│   ├── settings.py           # 配置加载 (config.yaml)
│   ├── agents/
│   │   ├── lead_agent.py     # Lead Agent 编排器
│   │   ├── sub_agents.py     # 5 个 Sub-Agent 定义
│   │   ├── batch_engine.py   # 批量处理引擎
│   │   ├── fallback.py       # 四级容错
│   │   ├── prompt_manager.py # Prompt 版本管理
│   │   └── context_budget.py # 上下文预算控制
│   ├── mcp/
│   │   └── fiber_backend.py  # MCP 工具连接器 (gRPC-HTTP)
│   ├── middlewares/
│   │   ├── rate_limit.py     # 令牌桶限流 (10/min)
│   │   ├── rag_injection.py  # RAG 注入中间件
│   │   ├── domain_validation.py # 领域校验
│   │   └── audit.py          # 审计日志
│   ├── rag/
│   │   ├── engine.py         # RAG 混合检索引擎
│   │   └── ingest.py         # 知识库文档导入
│   ├── memory/
│   │   └── store.py          # 短期+长期记忆存储
│   ├── monitoring/
│   │   ├── observability.py  # Trace/Metrics/结构化日志
│   │   └── metrics.py        # Prometheus 指标
│   ├── notify/
│   │   └── notifier.py       # 企微/邮件通知
│   ├── export/
│   │   └── exporters.py      # PDF/Excel 报告导出
│   └── plugins/
│       └── sdk.py            # 插件 SDK + 热加载
├── frontend/                 # Vue 3 前端
├── knowledge_base/           # 知识库 (6 类文档)
├── skills/                   # Agent 技能定义
├── plugins/                  # 自定义插件
├── config.yaml               # 配置中心
├── requirements.txt          # Python 依赖
├── Makefile                  # 常用命令
└── start_agent.bat           # Windows 一键启动
```

## 配置说明

核心配置在 `config.yaml`，支持环境变量覆盖 (`${VAR:default}`)：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `llm.model` | LLM 模型 | qwen3.6 |
| `llm.provider` | LLM 提供商 | ollama |
| `rag.embedding_model` | Embedding 模型 | nomic-embed-text |
| `backend.base_url` | 后端网关地址 | http://localhost:8080 |
| `agents.lead.temperature` | Lead Agent 温度 | 0.0 |
| `context_budget.total_tokens` | 总 Token 预算 | 8192 |
| `batch_engine.chunk_size` | 批处理分片大小 | 50 |

## AI 模型

| 模型 | 用途 | 部署方式 |
|------|------|----------|
| qwen3.6 | 对话/分析/报告 | Ollama 本地 |
| nomic-embed-text | 向量 Embedding | Ollama 本地 |

## 常用命令

```bash
make install    # 安装依赖
make dev        # 开发模式启动
make test       # 运行测试
make ingest     # 重建知识库索引
make up         # Docker 部署
make down       # 停止 Docker
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 对话接口 (SSE 流式) |
| WS | `/ws` | WebSocket 实时通信 |
| GET | `/health` | 健康检查 |
| POST | `/api/knowledge/ingest` | 上传知识库文档 |
| GET | `/api/knowledge/list` | 知识库文档列表 |
| GET | `/api/report/{id}` | 下载报告 |
| GET | `/api/observability/traces` | Trace 查询 |
| GET | `/api/observability/metrics` | Metrics 快照 |
| GET | `/metrics` | Prometheus 指标 |
# 🔬 光纤维护智能 Agent (Fiber Maintenance Agent)

基于 LLM + RAG + MCP 架构的下一代光纤网络运维助手。

## 🚀 快速开始

### 1. 环境准备
```bash
# 克隆项目并安装 Python 依赖
make install

# 启动前端面板
cd frontend && npm install && npm run dev