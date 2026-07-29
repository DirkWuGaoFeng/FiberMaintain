# FiberMaintain — 光纤维护服务系统

光纤网络端到端维护平台，包含 C++ 微服务后端 + Python AI Agent 智能运维助手。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (Vue 3 + Vite)                    │
│   Dashboard │ Chat │ Knowledge │ Observability           │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP :8080 / WebSocket :8081
┌────────────────────────┴────────────────────────────────┐
│                  API Gateway (C++)                        │
│          REST 路由 × 23 + CORS + WebSocket 代理          │
└────┬──────┬──────┬──────┬──────┬────────────────────────┘
     │      │      │      │      │  gRPC
 ┌───┴──┐┌──┴───┐┌─┴──┐┌┴───┐┌─┴──────┐  ┌──────────────┐
 │Board ││Topo  ││Perf││Alm ││FiberMnt│  │  Python Agent │
 │:50051││:50062││:53 ││:54 ││:50055  │  │  :8000        │
 └───┬──┘└──┬───┘└─┬──┘└┬───┘└─┬──────┘  │  LLM+RAG+MCP │
     └──────┴──────┴────┴──────┘          └──────────────┘
                    │ MySQL
     ┌──────────────┼──────────────┐
     │  db_board    │  db_topology  │  db_performance
     │  db_alarm    │  db_fiber_maint│
     └──────────────┴──────────────┘
```

## 目录结构

```
FiberMaintain/
├── Services/              # C++ 微服务后端
│   ├── src/
│   │   ├── common/        # 公共库（配置/日志/DB连接池/gRPC客户端）
│   │   ├── board_service/ # 板卡服务 (gRPC :50051)
│   │   ├── topology_service/  # 拓扑服务 (gRPC :50062)
│   │   ├── performance_service/ # 性能服务 (gRPC :50053)
│   │   ├── alarm_service/ # 告警服务 (gRPC :50054)
│   │   ├── fiber_maint_service/ # 光纤维护服务 (gRPC :50055)
│   │   ├── api_gateway/   # API 网关 (HTTP :8080, WS :8081)
│   │   ├── proto/         # Protobuf 接口定义 (6个)
│   │   └── simulators/    # 场景/告警/性能模拟器
│   ├── scripts/           # 启动/停止/数据库初始化脚本
│   ├── config/            # 服务配置文件 (.conf)
│   └── tests/             # C++ 集成测试
├── Agent/
│   └── fiber-maintenance-agent/   # Python AI Agent
│       ├── src/           # Agent 核心代码
│       │   ├── agents/    # Lead Agent + 5 Sub-Agent + 批量引擎 + 容错
│       │   ├── mcp/       # MCP 工具连接器
│       │   ├── middlewares/ # 中间件管道（限流/RAG/校验/审计）
│       │   ├── rag/       # RAG 引擎（向量+BM25混合检索）
│       │   ├── memory/    # 记忆存储（短期+长期）
│       │   ├── monitoring/ # 可观测性（Trace/Metrics/Logging）
│       │   ├── notify/    # 告警通知（企微/邮件）
│       │   ├── export/    # 报告导出（PDF/Excel）
│       │   └── plugins/   # 插件 SDK
│       ├── frontend/      # Vue 3 前端
│       ├── knowledge_base/ # 知识库（6类文档）
│       ├── skills/        # Agent 技能定义 (.md)
│       └── config.yaml    # Agent 配置中心
└── docs/                  # 项目文档
```

## 技术栈

| 层级 | 技术 |
|------|------|
| C++ 后端 | C++17, gRPC 1.30, Protobuf 3.12, libmicrohttpd, MySQL |
| AI Agent | Python 3.10+, FastAPI, LangGraph, Ollama (qwen3.6) |
| RAG | ChromaDB, BM25, nomic-embed-text (Ollama 本地) |
| 前端 | Vue 3, Vite, ECharts, Element Plus |
| 可观测性 | SQLite Trace (7d), Prometheus Metrics, 结构化 JSON Log |

## 快速开始

### 1. 编译 C++ 微服务（WSL Ubuntu）

```bash
cd /mnt/e/Work/FiberMaintain/Services
mkdir -p build && cd build
cmake ..
make -j4
```

### 2. 初始化数据库

```bash
mysql -u root -p < scripts/init_database.sql
```

### 3. 启动微服务

```bash
# 一键启动全部6个服务
bash scripts/start_services.sh

# 一键停止
bash scripts/stop_services.sh
```

### 4. 启动 Agent（Windows）

```bat
cd Agent\fiber-maintenance-agent
start_agent.bat
```

### 5. 启动前端

```bash
cd Agent/fiber-maintenance-agent/frontend
npm install && npm run dev
```

## 服务端口

| 服务 | 端口 | 协议 |
|------|------|------|
| BoardService | 50051 | gRPC |
| TopologyService | 50062 | gRPC |
| PerformanceService | 50053 | gRPC |
| AlarmService | 50054 | gRPC |
| FiberMaintService | 50055 | gRPC |
| API Gateway | 8080 | HTTP REST |
| API Gateway WS | 8081 | WebSocket |
| Agent | 8000 | HTTP + SSE |
| 前端 | 5173 | HTTP (dev) |

## 本地 AI 模型

- **LLM**: Ollama 部署 qwen3.6
- **Embedding**: Ollama 部署 nomic-embed-text
- 配置详见 `Agent/fiber-maintenance-agent/config.yaml`

## 文档

- [架构设计](docs/架构设计.md)
- [接口文档](docs/接口文档.md)
- [需求规格说明书](docs/需求规格说明书.md)
- [Agent 详细设计报告 v3.2.1](Agent/docs/光纤维护服务系统 Agent 详细设计报告 v3.2.1.md)
- [测试报告](docs/详细测试报告.md)
